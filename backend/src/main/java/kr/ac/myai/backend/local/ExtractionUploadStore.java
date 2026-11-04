package kr.ac.myai.backend.local;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import kr.ac.myai.backend.exception.ApiException;
import kr.ac.myai.backend.importing.ImportException;
import kr.ac.myai.backend.importing.ReviewedImportReader;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Profile;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Component;

import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.nio.file.attribute.BasicFileAttributes;
import java.nio.file.attribute.PosixFilePermission;
import java.nio.file.attribute.PosixFilePermissions;
import java.util.*;

@Component
@Profile("local-api")
public class ExtractionUploadStore {
    private static final int CONTROL_LIMIT = 64 * 1024;
    private static final int INPUT_LIMIT = 8 * 1024 * 1024;
    private static final int PROMPT_LIMIT = 20 * 1024 * 1024;
    private static final int OUTPUT_LIMIT = 5 * 1024 * 1024;
    private static final List<String> INITIAL_FILES = List.of("control.json", "metadata.json", "input.json");
    private static final Set<PosixFilePermission> DIRECTORY_MODE = PosixFilePermissions.fromString("rwx------");
    private static final Set<PosixFilePermission> FILE_MODE = PosixFilePermissions.fromString("rw-------");
    private final String configuredRoot;
    private final ReviewedImportReader json;
    private final ObjectMapper mapper = new ObjectMapper();

    public ExtractionUploadStore(@Value("${myai.local-api.request-root}") String configuredRoot, ReviewedImportReader json) {
        this.configuredRoot = configuredRoot;
        this.json = json;
    }

    public record Artifact(String name, long sizeBytes, String sha256) { }
    public record Staged(String runId, String expectedInputHash, int attempts, Path directory, byte[] control, List<Artifact> artifacts) {
        public Staged { control = control.clone(); artifacts = List.copyOf(artifacts); }
        @Override public byte[] control() { return control.clone(); }
    }

    public Staged initialize(String runId, String expectedInputHash, int attempts, byte[] control, byte[] metadata, byte[] input) {
        request(runId, expectedInputHash);
        if (attempts < 1 || attempts > 3) throw invalid();
        content(control, CONTROL_LIMIT, false); content(metadata, CONTROL_LIMIT, false); content(input, INPUT_LIMIT, false);
        if (!ReviewedImportReader.sha256(input).equals(expectedInputHash)) throw invalid();
        try {
            Path uploads = createDirectory(root().resolve("extraction-uploads"));
            Path index = uploads.resolve(runId + ".json");
            if (Files.exists(index, LinkOption.NOFOLLOW_LINKS)) return matching(load(index, runId), expectedInputHash, attempts, control, metadata, input);
            Path bundles = createDirectory(uploads.resolve("bundles"));
            String bundleId = UUID.randomUUID().toString();
            Path bundle = Files.createDirectory(bundles.resolve(bundleId), PosixFilePermissions.asFileAttribute(DIRECTORY_MODE));
            Path temporary = null;
            boolean installed = false;
            try {
                write(bundle.resolve("control.json"), control);
                write(bundle.resolve("metadata.json"), metadata);
                write(bundle.resolve("input.json"), input);
                var identity = mapper.createObjectNode().put("run_id", runId).put("expected_input_hash", expectedInputHash).put("attempts", attempts);
                var files = identity.putObject("files");
                files.set("control.json", descriptor("control.json", control));
                files.set("metadata.json", descriptor("metadata.json", metadata));
                files.set("input.json", descriptor("input.json", input));
                byte[] identityBytes = bytes(identity);
                write(bundle.resolve("identity.json"), identityBytes);
                loadBundle(bundle, runId, ReviewedImportReader.sha256(identityBytes));
                var reference = mapper.createObjectNode().put("bundle_id", bundleId).put("identity_sha256", ReviewedImportReader.sha256(identityBytes));
                temporary = temporary(uploads, bytes(reference));
                try { Files.createLink(index, temporary); installed = true; }
                catch (FileAlreadyExistsException ex) { return matching(load(index, runId), expectedInputHash, attempts, control, metadata, input); }
                return load(index, runId);
            } finally {
                if (temporary != null) Files.deleteIfExists(temporary);
                if (!installed) {
                    for (String name : INITIAL_FILES) Files.deleteIfExists(bundle.resolve(name));
                    Files.deleteIfExists(bundle.resolve("identity.json"));
                    Files.deleteIfExists(bundle);
                }
            }
        } catch (IOException | IllegalArgumentException | UnsupportedOperationException | SecurityException ex) { throw ioError(); }
    }

    public Optional<Staged> find(String runId) {
        if (!uuid(runId)) throw invalid();
        try {
            Path uploads = root().resolve("extraction-uploads");
            if (!Files.exists(uploads, LinkOption.NOFOLLOW_LINKS)) return Optional.empty();
            directory(uploads);
            Path index = uploads.resolve(runId + ".json");
            return Files.exists(index, LinkOption.NOFOLLOW_LINKS) ? Optional.of(load(index, runId)) : Optional.empty();
        } catch (IOException | IllegalArgumentException | UnsupportedOperationException | SecurityException ex) { throw ioError(); }
    }

    public Staged put(String runId, int attempt, String artifact, byte[] content) {
        if (!uuid(runId) || attempt < 1 || attempt > 3 || !("prompt".equals(artifact) || "output".equals(artifact))) throw invalid();
        int limit = "prompt".equals(artifact) ? PROMPT_LIMIT : OUTPUT_LIMIT;
        content(content, limit, true);
        var staged = find(runId).orElseThrow(this::notFound);
        if (attempt > staged.attempts()) throw invalid();
        String name = "attempt-" + attempt + "." + artifact;
        try {
            Path uploads = root().resolve("extraction-uploads"); directory(uploads);
            install(staged.directory().resolve(name), content, limit, uploads);
            // 원본 설치 뒤 중단되면 같은 bytes로 이 불변 크기/hash 기록만 이어서 설치한다.
            install(staged.directory().resolve(name + ".identity.json"), bytes(descriptor(name, content)), CONTROL_LIMIT, uploads);
            return find(runId).orElseThrow(this::notFound);
        } catch (IOException | IllegalArgumentException | UnsupportedOperationException | SecurityException ex) { throw ioError(); }
    }

    public Staged ready(String runId, String expectedInputHash) {
        request(runId, expectedInputHash);
        var staged = find(runId).orElseThrow(this::notFound);
        if (!staged.expectedInputHash().equals(expectedInputHash)) throw conflict();
        if (staged.artifacts().size() != INITIAL_FILES.size() + staged.attempts() * 2) throw invalid();
        return staged;
    }

    private Staged load(Path index, String runId) throws IOException {
        JsonNode reference = parse(read(index, CONTROL_LIMIT));
        if (!fields(reference, Set.of("bundle_id", "identity_sha256")) || !uuid(reference.path("bundle_id").textValue())
                || !hash(reference.path("identity_sha256").textValue())) throw conflict();
        Path bundles = index.getParent().resolve("bundles"); directory(bundles);
        return loadBundle(bundles.resolve(reference.path("bundle_id").textValue()), runId, reference.path("identity_sha256").textValue());
    }

    private Staged loadBundle(Path bundle, String runId, String identityHash) throws IOException {
        directory(bundle);
        byte[] identityBytes = read(bundle.resolve("identity.json"), CONTROL_LIMIT);
        if (!ReviewedImportReader.sha256(identityBytes).equals(identityHash)) throw conflict();
        JsonNode identity = parse(identityBytes);
        if (!fields(identity, Set.of("run_id", "expected_input_hash", "attempts", "files"))
                || !runId.equals(identity.path("run_id").textValue()) || !hash(identity.path("expected_input_hash").textValue())
                || !identity.path("attempts").isIntegralNumber() || !identity.path("attempts").canConvertToInt()
                || identity.path("attempts").intValue() < 1 || identity.path("attempts").intValue() > 3
                || !fields(identity.path("files"), Set.copyOf(INITIAL_FILES))) throw conflict();
        int attempts = identity.path("attempts").intValue();
        var allowed = new HashSet<>(INITIAL_FILES); allowed.add("identity.json");
        for (int attempt = 1; attempt <= attempts; attempt++) for (String artifact : List.of("prompt", "output")) {
            String name = "attempt-" + attempt + "." + artifact;
            allowed.add(name); allowed.add(name + ".identity.json");
        }
        try (var files = Files.newDirectoryStream(bundle)) {
            for (Path file : files) if (!allowed.contains(file.getFileName().toString())) throw conflict();
        }
        var artifacts = new ArrayList<Artifact>();
        byte[] control = null;
        for (String name : INITIAL_FILES) {
            byte[] original = read(bundle.resolve(name), name.equals("input.json") ? INPUT_LIMIT : CONTROL_LIMIT);
            if (original.length == 0) throw conflict();
            artifacts.add(verified(identity.path("files").path(name), name, original));
            if (name.equals("control.json")) control = original;
        }
        String expectedInputHash = identity.path("expected_input_hash").textValue();
        if (!expectedInputHash.equals(identity.path("files").path("input.json").path("sha256").textValue())) throw conflict();
        for (int attempt = 1; attempt <= attempts; attempt++) for (String artifact : List.of("prompt", "output")) {
            String name = "attempt-" + attempt + "." + artifact;
            Path file = bundle.resolve(name), record = bundle.resolve(name + ".identity.json");
            boolean recordExists = Files.exists(record, LinkOption.NOFOLLOW_LINKS), originalExists = Files.exists(file, LinkOption.NOFOLLOW_LINKS);
            if (recordExists && !originalExists) throw conflict();
            if (originalExists) {
                byte[] original = read(file, artifact.equals("prompt") ? PROMPT_LIMIT : OUTPUT_LIMIT);
                if (recordExists) artifacts.add(verified(parse(read(record, CONTROL_LIMIT)), name, original));
            }
        }
        return new Staged(runId, expectedInputHash, attempts, bundle, control, artifacts);
    }

    private Staged matching(Staged staged, String hash, int attempts, byte[] control, byte[] metadata, byte[] input) throws IOException {
        if (!staged.expectedInputHash().equals(hash) || staged.attempts() != attempts || !Arrays.equals(staged.control(), control)
                || !Arrays.equals(read(staged.directory().resolve("metadata.json"), CONTROL_LIMIT), metadata)
                || !Arrays.equals(read(staged.directory().resolve("input.json"), INPUT_LIMIT), input)) throw conflict();
        return staged;
    }

    private ObjectNode descriptor(String name, byte[] content) {
        return mapper.createObjectNode().put("name", name).put("size_bytes", content.length).put("sha256", ReviewedImportReader.sha256(content));
    }

    private Artifact verified(JsonNode descriptor, String name, byte[] content) {
        if (!fields(descriptor, Set.of("name", "size_bytes", "sha256")) || !name.equals(descriptor.path("name").textValue())
                || !descriptor.path("size_bytes").isIntegralNumber() || !descriptor.path("size_bytes").canConvertToLong()
                || descriptor.path("size_bytes").longValue() != content.length
                || !ReviewedImportReader.sha256(content).equals(descriptor.path("sha256").textValue())) throw conflict();
        return new Artifact(name, content.length, descriptor.path("sha256").textValue());
    }

    private void install(Path target, byte[] content, int limit, Path uploads) throws IOException {
        if (Files.exists(target, LinkOption.NOFOLLOW_LINKS)) {
            if (!Arrays.equals(read(target, limit), content)) throw conflict();
            return;
        }
        Path temporary = temporary(uploads, content);
        try {
            try { Files.createLink(target, temporary); }
            catch (FileAlreadyExistsException ex) { if (!Arrays.equals(read(target, limit), content)) throw conflict(); }
        } finally { Files.deleteIfExists(temporary); }
    }

    private Path temporary(Path directory, byte[] content) throws IOException {
        Path temporary = Files.createTempFile(directory, ".extraction-", ".tmp", PosixFilePermissions.asFileAttribute(FILE_MODE));
        boolean written = false;
        try {
            Files.write(temporary, content, StandardOpenOption.WRITE, LinkOption.NOFOLLOW_LINKS);
            written = true; return temporary;
        } finally { if (!written) Files.deleteIfExists(temporary); }
    }

    private void write(Path file, byte[] content) throws IOException {
        try (var channel = Files.newByteChannel(file, Set.of(StandardOpenOption.CREATE_NEW, StandardOpenOption.WRITE),
                PosixFilePermissions.asFileAttribute(FILE_MODE))) {
            var buffer = ByteBuffer.wrap(content);
            while (buffer.hasRemaining()) channel.write(buffer);
        }
    }

    private byte[] read(Path file, int limit) throws IOException {
        if (!Files.isRegularFile(file, LinkOption.NOFOLLOW_LINKS)
                || !Files.getPosixFilePermissions(file, LinkOption.NOFOLLOW_LINKS).equals(FILE_MODE)) throw conflict();
        var before = Files.readAttributes(file, BasicFileAttributes.class, LinkOption.NOFOLLOW_LINKS);
        try (var stream = Files.newInputStream(file, StandardOpenOption.READ, LinkOption.NOFOLLOW_LINKS)) {
            byte[] content = stream.readNBytes(limit + 1);
            var after = Files.readAttributes(file, BasicFileAttributes.class, LinkOption.NOFOLLOW_LINKS);
            if (content.length > limit || !after.isRegularFile() || content.length != after.size()
                    || !Objects.equals(before.fileKey(), after.fileKey()) || before.size() != after.size()
                    || !before.lastModifiedTime().equals(after.lastModifiedTime())
                    || !Files.getPosixFilePermissions(file, LinkOption.NOFOLLOW_LINKS).equals(FILE_MODE)) throw conflict();
            return content;
        }
    }

    private Path root() throws IOException {
        if (configuredRoot == null || configuredRoot.isBlank()) throw ioError();
        Path stated = Path.of(configuredRoot);
        if (!stated.isAbsolute() || !stated.normalize().equals(stated)) throw ioError();
        Path current = stated.getRoot();
        for (Path part : stated) {
            current = current.resolve(part);
            if (!Files.isDirectory(current, LinkOption.NOFOLLOW_LINKS)) throw ioError();
        }
        if (!Files.getPosixFilePermissions(stated, LinkOption.NOFOLLOW_LINKS).equals(DIRECTORY_MODE)) throw ioError();
        return stated;
    }

    private Path createDirectory(Path path) throws IOException {
        try { Files.createDirectory(path, PosixFilePermissions.asFileAttribute(DIRECTORY_MODE)); }
        catch (FileAlreadyExistsException ignored) { }
        directory(path); return path;
    }

    private void directory(Path path) throws IOException {
        if (!Files.isDirectory(path, LinkOption.NOFOLLOW_LINKS)
                || !Files.getPosixFilePermissions(path, LinkOption.NOFOLLOW_LINKS).equals(DIRECTORY_MODE)) throw conflict();
    }

    private JsonNode parse(byte[] content) {
        try { return json.parseJson(content); }
        catch (ImportException ex) { throw conflict(); }
    }

    private boolean fields(JsonNode node, Set<String> expected) {
        if (node == null || !node.isObject()) return false;
        var actual = new HashSet<String>(); node.fieldNames().forEachRemaining(actual::add); return actual.equals(expected);
    }

    private void content(byte[] content, int limit, boolean emptyAllowed) {
        if (content == null || !emptyAllowed && content.length == 0) throw invalid();
        if (content.length > limit) throw new ApiException(HttpStatus.PAYLOAD_TOO_LARGE, "EXTRACTION_UPLOAD_TOO_LARGE", "업로드 파일 크기 한도를 초과했습니다.", null);
    }

    private void request(String runId, String hash) { if (!uuid(runId) || !hash(hash)) throw invalid(); }
    private boolean uuid(String value) { return value != null && value.matches("[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"); }
    private boolean hash(String value) { return value != null && value.matches("[0-9a-f]{64}"); }
    private byte[] bytes(JsonNode value) { return value.toString().getBytes(StandardCharsets.UTF_8); }
    private ApiException invalid() { return new ApiException(HttpStatus.UNPROCESSABLE_ENTITY, "EXTRACTION_UPLOAD_INVALID", "업로드 식별자·입력 해시·시도 번호와 파일 쌍을 확인해 주세요.", null); }
    private ApiException conflict() { return new ApiException(HttpStatus.CONFLICT, "EXTRACTION_UPLOAD_CONFLICT", "업로드 원본·검증 기록·링크 또는 권한이 다릅니다. 기존 항목을 보존했습니다.", null); }
    private ApiException notFound() { return new ApiException(HttpStatus.NOT_FOUND, "EXTRACTION_UPLOAD_NOT_FOUND", "초기화한 업로드 실행을 찾을 수 없습니다.", null); }
    private ApiException ioError() { return new ApiException(HttpStatus.INTERNAL_SERVER_ERROR, "EXTRACTION_UPLOAD_IO_ERROR", "비공개 업로드 원본을 읽거나 보관하지 못했습니다.", null); }
}
