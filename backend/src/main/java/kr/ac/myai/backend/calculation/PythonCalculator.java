package kr.ac.myai.backend.calculation;

import com.fasterxml.jackson.core.JsonProcessingException;
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

import java.util.HashSet;
import java.util.Set;
import java.util.concurrent.Semaphore;

@Component
@Profile("!fixture")
public class PythonCalculator {
    private final Semaphore slots = new Semaphore(4);
    private final ObjectMapper mapper;
    private final ReviewedImportReader json;
    private final String executable;
    private final String workdir;
    private final long timeoutMillis;

    public PythonCalculator(ObjectMapper mapper, ReviewedImportReader json,
                            @Value("${app.calculation.python-executable:python3.13}") String executable,
                            @Value("${app.calculation.workdir:}") String workdir,
                            @Value("${app.calculation.timeout-ms:5000}") long timeoutMillis) {
        this.mapper = mapper; this.json = json; this.executable = executable;
        this.workdir = workdir; this.timeoutMillis = timeoutMillis;
    }

    public ObjectNode calculate(ObjectNode request) {
        if (Thread.currentThread().isInterrupted() || !slots.tryAcquire()) throw unavailable(true);
        try {
            byte[] input;
            try { input = mapper.writeValueAsBytes(request); }
            catch (JsonProcessingException ex) { throw protocolError(); }
            byte[] output = execute(input);
            try {
                JsonNode response = json.parseJson(output);
                require(keys(response).equals(Set.of("protocol_version", "request_id", "snapshot_id", "input_sha256", "rules_version", "data", "diagnostics")));
                require(response.path("protocol_version").asText().equals("calc-v1"));
                for (String key : Set.of("request_id", "snapshot_id")) require(response.path(key).equals(request.path(key)));
                require(response.path("input_sha256").asText().equals(ReviewedImportReader.sha256(input)));
                require(response.path("rules_version").equals(request.path("context").path("rules_version")));
                require(response.path("data").isObject() && response.path("diagnostics").isArray());
                return (ObjectNode) response.path("data");
            } catch (ImportException ex) { throw protocolError(); }
        } finally { slots.release(); }
    }

    private byte[] execute(byte[] input) {
        try {
            // 실행 파일·작업 폴더·제한 시간·입력 크기는 PythonProcess가 검사한다. 비밀값은 물려주지 않는다.
            var result = kr.ac.myai.backend.process.PythonProcess.executeKeyless(executable, workdir,
                    java.util.List.of("-B", "-s", "-m", "processing.matching"), input, timeoutMillis);
            if (result.exitCode() != 0) throw unavailable(false);
            return result.stdout();
        } catch (kr.ac.myai.backend.process.PythonProcess.Failure ex) {
            throw unavailable(ex.retryable());
        }
    }

    static Set<String> keys(JsonNode node) {
        var keys = new HashSet<String>(); node.fieldNames().forEachRemaining(keys::add); return keys;
    }

    public static void require(boolean condition) { if (!condition) throw protocolError(); }

    public static void shape(JsonNode node, String fields) {
        require(node.isObject() && keys(node).equals(Set.of(fields.split(" "))));
    }

    public static ApiException protocolError() {
        return new ApiException(HttpStatus.INTERNAL_SERVER_ERROR, "CALCULATION_PROTOCOL_ERROR", "계산 응답의 무결성을 확인할 수 없습니다.", null);
    }

    private static ApiException unavailable(boolean retryable) {
        return new ApiException(HttpStatus.SERVICE_UNAVAILABLE, "CALCULATION_UNAVAILABLE", "계산기를 사용할 수 없습니다.", null, retryable);
    }
}
