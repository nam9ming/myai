package kr.ac.myai.backend.local;

import kr.ac.myai.backend.exception.ApiException;
import kr.ac.myai.backend.importing.ReviewedImportReader;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Profile;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Component;

import java.io.IOException;
import java.nio.file.FileAlreadyExistsException;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.nio.file.attribute.PosixFilePermissions;
import java.util.Arrays;

@Component
@Profile("local-api")
public class LocalRequestStore {
    private static final int LIMIT = 8 * 1024 * 1024;
    private final String configuredRoot;

    public LocalRequestStore(@Value("${myai.local-api.request-root}") String root) {
        this.configuredRoot = root;
    }

    public Path retain(byte[] content) {
        if (content == null || content.length == 0 || content.length > LIMIT) {
            throw new ApiException(HttpStatus.UNPROCESSABLE_ENTITY, "LOCAL_API_VALIDATION_ERROR", "요청 본문은1바이트 이상8MiB 이하로 전달해 주세요.", null);
        }
        try {
            Path directory = directory();
            Path target = directory.resolve(ReviewedImportReader.sha256(content) + ".json");
            if (Files.exists(target, LinkOption.NOFOLLOW_LINKS)) return existing(target, content);
            Path temporary = Files.createTempFile(directory, ".request-", ".tmp", PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rw-------")));
            try {
                Files.write(temporary, content, StandardOpenOption.WRITE);
                try { Files.createLink(target, temporary); }
                catch (FileAlreadyExistsException ex) { return existing(target, content); }
                return target;
            } finally { Files.deleteIfExists(temporary); }
        } catch (IOException | IllegalArgumentException | UnsupportedOperationException | SecurityException ex) {
            throw ioError();
        }
    }

    private Path directory() throws IOException {
        if (configuredRoot == null || configuredRoot.isBlank()) throw ioError();
        Path stated = Path.of(configuredRoot);
        if (!stated.isAbsolute()) throw ioError();
        Path current = stated.getRoot();
        for (Path part : stated) {
            current = current.resolve(part);
            if (!Files.isDirectory(current, LinkOption.NOFOLLOW_LINKS)) throw ioError();
        }
        if (!Files.getPosixFilePermissions(current, LinkOption.NOFOLLOW_LINKS).equals(PosixFilePermissions.fromString("rwx------"))) throw ioError();
        return current.normalize();
    }

    private Path existing(Path target, byte[] content) throws IOException {
        if (Files.isRegularFile(target, LinkOption.NOFOLLOW_LINKS)
                && Files.getPosixFilePermissions(target, LinkOption.NOFOLLOW_LINKS).equals(PosixFilePermissions.fromString("rw-------"))) {
            try (var input = Files.newInputStream(target, StandardOpenOption.READ, LinkOption.NOFOLLOW_LINKS)) {
                if (Arrays.equals(content, input.readNBytes(content.length + 1))) return target;
            }
        }
        throw new ApiException(HttpStatus.CONFLICT, "LOCAL_API_REQUEST_CONFLICT", "요청 보관 위치에 다른 내용·링크 또는 안전하지 않은 권한의 파일이 있습니다. 기존 항목을 보존했습니다.", null);
    }

    private ApiException ioError() {
        return new ApiException(HttpStatus.INTERNAL_SERVER_ERROR, "LOCAL_API_IO_ERROR", "요청 원본을 저장하지 못했습니다. 비공개 보관 디렉터리와 접근 권한을 확인해 주세요.", null);
    }
}
