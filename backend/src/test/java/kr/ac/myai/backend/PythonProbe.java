package kr.ac.myai.backend;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;

final class PythonProbe {
    static final Path REPO = Path.of("..").toAbsolutePath().normalize();
    static final String PYTHON = System.getenv().getOrDefault("MYAI_PYTHON_EXECUTABLE", "python3.13");
    static final String ECHO = """
            raw = sys.stdin.buffer.read()
            request = json.loads(raw)
            response = dict(protocol_version='calc-v1', request_id=request['request_id'],
                            snapshot_id=request['snapshot_id'], input_sha256=hashlib.sha256(raw).hexdigest(),
                            rules_version=request['context']['rules_version'], data={}, diagnostics=[])
            """;

    static Path create(Path base, String body) throws Exception {
        Path root = Files.createTempDirectory(base, "python-probe-");
        Path module = Files.createDirectories(root.resolve("processing/matching"));
        Files.writeString(root.resolve("processing/__init__.py"), "");
        Files.writeString(module.resolve("__init__.py"), "");
        Files.writeString(module.resolve("__main__.py"), """
                import sys, os, time, json, hashlib
                from pathlib import Path
                Path('pid-' + str(os.getpid())).write_text(str(os.getpid()))
                """ + body);
        return root;
    }

    static List<ProcessHandle> processes(Path root) throws Exception {
        try (var files = Files.walk(root)) {
            var result = new java.util.ArrayList<ProcessHandle>();
            for (Path file : files.filter(p -> p.getFileName().toString().startsWith("pid-")).toList()) {
                var handle = ProcessHandle.of(Long.parseLong(file.getFileName().toString().substring(4)));
                if (handle.isEmpty()) continue;
                var started = handle.get().info().startInstant();
                if (started.isPresent() && !started.get().isAfter(Files.getLastModifiedTime(file).toInstant())) result.add(handle.get());
                else if (started.isEmpty() && handle.get().isAlive()) throw new AssertionError("Cannot identify test process");
            }
            return result;
        }
    }

    static Path realEngine(Path base, String mutation) throws Exception {
        Path root = create(base, """
                from .protocol import run
                raw = sys.stdin.buffer.read()
                request = json.loads(raw)
                response = run(raw)
                """ + mutation + "\nprint(json.dumps(response, ensure_ascii=False))");
        var mapper = new com.fasterxml.jackson.databind.ObjectMapper();
        Files.writeString(root.resolve("processing/__init__.py"), "__path__.append(" + mapper.writeValueAsString(REPO.resolve("processing").toString()) + ")");
        Files.writeString(root.resolve("processing/matching/__init__.py"), "__path__.append(" + mapper.writeValueAsString(REPO.resolve("processing/matching").toString()) + ")");
        return root;
    }

    static void waitForStarts(Path root, int count) throws Exception {
        long deadline = System.nanoTime() + 3_000_000_000L;
        while (System.nanoTime() < deadline) {
            if (processes(root).stream().filter(ProcessHandle::isAlive).count() >= count) return;
            Thread.sleep(10);
        }
        throw new AssertionError("Python probe did not start");
    }

    static void stopAll(Path root) throws Exception {
        for (var process : processes(root)) if (process.isAlive()) process.destroyForcibly();
    }

    private PythonProbe() {}
}
