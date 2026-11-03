package kr.ac.myai.backend;

import com.fasterxml.jackson.databind.ObjectMapper;
import kr.ac.myai.backend.importing.ReviewedImportReader;
import kr.ac.myai.backend.publication.PublicationContent;
import kr.ac.myai.backend.repository.PublicSnapshotRepository;
import kr.ac.myai.backend.service.SnapshotExportService;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.SimpleTransactionStatus;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.attribute.PosixFilePermissions;
import java.util.Optional;
import java.util.UUID;
import java.util.concurrent.TimeUnit;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

class UserStudyMaterialTest {
    @TempDir Path root;

    @Test
    void actualJavaExportBindsToPrivatePythonStudyWithoutRewritingSnapshot() throws Exception {
        Files.setPosixFilePermissions(root, PosixFilePermissions.fromString("rwx------"));
        var mapper = new ObjectMapper();
        var published = CalculationFixtures.published(CalculationFixtures.snapshot(mapper), mapper);
        var repository = mock(PublicSnapshotRepository.class);
        var transactions = mock(PlatformTransactionManager.class);
        when(repository.published(published.snapshot().id())).thenReturn(Optional.of(published));
        when(transactions.getTransaction(any())).thenAnswer(call -> new SimpleTransactionStatus());
        var service = new SnapshotExportService(repository, new PublicationContent(new ReviewedImportReader(), mapper), transactions);
        var exported = service.export(UUID.fromString(published.snapshot().id()), root);
        Path file = root.resolve(exported.fileName()); byte[] original = Files.readAllBytes(file);
        String script = """
                import csv, hashlib, io, json, subprocess, sys
                from pathlib import Path
                from processing.tests.test_user_study import UserStudyFixture
                fixture = UserStudyFixture()
                try:
                    fixture.setUp()
                    raw = Path(sys.argv[1]).read_bytes()
                    assert hashlib.sha256(raw).hexdigest() == sys.argv[2]
                    snapshot = json.loads(raw)
                    protocol = fixture.protocol
                    protocol['data_kind'] = snapshot['data_kind']
                    protocol['versions'].update({key: snapshot[key] for key in ('snapshot_id','rules_version','dictionary_version')})
                    protocol['versions']['snapshot_checksum'] = sys.argv[2]
                    material = protocol['source_set']
                    material['snapshot_artifact'] = fixture.artifact('materials/java-snapshot.json', raw)
                    documents = []
                    for index, source in enumerate(snapshot['sources']):
                        document = {key: source[key] for key in ('document_id','document_version_id','official_url','text_sha256')}
                        document['artifact'] = fixture.artifact(f'materials/java-source-{index}.txt', b'SYNTHETIC raw asset, not original D03 body')
                        documents.append(document)
                    material['documents'] = documents
                    versions = [document['document_version_id'] for document in documents]
                    material['board_document_version_ids'] = material['prototype_document_version_ids'] = versions
                    event = snapshot['event_public_payloads'][0]['event_id']
                    for group in protocol['task_sets']:
                        for task in group['items']:
                            task['expected_event_ids'] = [event] if task['expected_event_ids'] else []
                    fixture.records['protocol_sha256'] = hashlib.sha256(fixture.protocol_bytes()).hexdigest()
                    fixture.records['participants'] = [fixture.person()]
                    fixture.records['recruitment'] = [dict(participant_id=fixture.records['participants'][0]['participant_id'], status='consented')]
                    fixture.write_records()
                    common = ['--root', str(fixture.work), '--protocol', 'protocol.json', '--input', 'records.json']
                    def run(*args):
                        result = subprocess.run([sys.executable, '-B', '-m', 'processing.evaluation', *args], capture_output=True, timeout=15)
                        assert result.returncode == 0, result.stderr
                        assert result.stderr == b'' and result.stdout.count(b'\\n') == 1
                        assert b'PRIVATE_' not in result.stdout
                        return json.loads(result.stdout)
                    checked = run('check-study', *common)
                    assert checked['primary']['eligible_pairs'] == 1
                    assert checked['primary']['meets_20_percent_as_declared'] is None
                    first = run('export-study', *common, '--output', 'reports/result.json', '--format', 'json')
                    assert run('export-study', *common, '--output', 'reports/result.json', '--format', 'json') == first
                    run('export-study', *common, '--output', 'reports/result.csv', '--format', 'csv')
                    rows = list(csv.DictReader(io.StringIO((fixture.work/'reports/result.csv').read_text())))
                    assert len(rows) == 7
                    assert (fixture.work/'materials/java-snapshot.json').read_bytes() == raw
                    print(json.dumps(dict(protocol_version='user-study-summary-v1', documents=len(documents), events=len(snapshot['event_public_payloads']), task_rows=6)))
                finally:
                    fixture.doCleanups()
                """;
        var command = new ProcessBuilder(PythonProbe.PYTHON, "-B", "-c", script, file.toString(), exported.checksum())
                .directory(PythonProbe.REPO.toFile()).redirectErrorStream(true);
        command.environment().put("PYTHONPATH", PythonProbe.REPO.resolve("processing/tests") + java.io.File.pathSeparator + PythonProbe.REPO);
        command.environment().put("TMPDIR", root.toString());
        var process = command.start();
        try {
            boolean exited = process.waitFor(30, TimeUnit.SECONDS);
            if (!exited) process.descendants().forEach(ProcessHandle::destroyForcibly);
            assertThat(exited).isTrue();
            String output = new String(process.getInputStream().readAllBytes(), StandardCharsets.UTF_8);
            assertThat(process.exitValue()).as(output).isZero();
            assertThat(mapper.readTree(output).path("protocol_version").asText()).isEqualTo("user-study-summary-v1");
            assertThat(mapper.readTree(output).path("task_rows").asInt()).isEqualTo(6);
            assertThat(Files.readAllBytes(file)).isEqualTo(original);
        } finally {
            if (process.isAlive()) { process.descendants().forEach(ProcessHandle::destroyForcibly); process.destroyForcibly(); }
        }
    }
}
