package kr.ac.myai.backend.calculation;

import com.fasterxml.jackson.databind.node.JsonNodeFactory;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.math.BigInteger;

import static org.assertj.core.api.Assertions.assertThat;

class CalculationResponseNumberTest {
    private final JsonNodeFactory nodes = JsonNodeFactory.instance;

    @Test
    void decimalsMatchAsDoublesButIntegersMustMatchExactly() {
        var comparator = CalculationResponse.SAME_NUMBER;
        // 좌표처럼 Python이 double로 돌려주는 소수는 같은 double이면 같다.
        assertThat(comparator.compare(nodes.numberNode(new BigDecimal("127.270000000000001")), nodes.numberNode(127.27))).isZero();
        // 2^53을 넘는 서로 다른 정수는 double로는 같아도 다르다.
        assertThat(comparator.compare(nodes.numberNode(new BigInteger("9007199254740992")),
                nodes.numberNode(new BigInteger("9007199254740993")))).isNotZero();
        assertThat(comparator.compare(nodes.textNode("1"), nodes.numberNode(1))).isNotZero();
        assertThat(comparator.compare(nodes.numberNode(1), nodes.numberNode(new BigDecimal("1.0")))).isNotZero();
    }
}
