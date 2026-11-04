package kr.ac.myai.backend.logging;

import jakarta.servlet.http.HttpServletRequest;
import org.springframework.web.context.request.RequestContextHolder;
import org.springframework.web.context.request.ServletRequestAttributes;

import java.util.UUID;

public final class PublicRequestLogContext {
    private static final String ATTRIBUTE = PublicRequestLogContext.class.getName() + ".state";

    private PublicRequestLogContext() {}

    public static String requestId() {
        State state = current();
        return state == null ? UUID.randomUUID().toString() : state.requestId;
    }

    public static void selected(String snapshotId, String rulesVersion) {
        State state = current();
        if (state == null) return;
        state.snapshotId = snapshot(snapshotId);
        state.rulesVersion = rules(rulesVersion);
        state.selected = state.snapshotId != null;
    }

    public static void response(String snapshotId, String rulesVersion) {
        State state = current();
        if (state == null || state.selected) return;
        state.snapshotId = snapshot(snapshotId);
        state.rulesVersion = rules(rulesVersion);
    }

    public static void error(String code) {
        State state = current();
        if (state != null) state.errorCode = code != null && code.matches("[A-Z][A-Z_]{0,99}") ? code : null;
    }

    static State initialize(HttpServletRequest request) {
        State state = new State(UUID.randomUUID().toString());
        request.setAttribute(ATTRIBUTE, state);
        return state;
    }

    static State state(HttpServletRequest request) {
        return request.getAttribute(ATTRIBUTE) instanceof State state ? state : null;
    }

    private static State current() {
        return RequestContextHolder.getRequestAttributes() instanceof ServletRequestAttributes attributes
                ? state(attributes.getRequest()) : null;
    }

    private static String snapshot(String value) {
        if (value == null) return null;
        try {
            return UUID.fromString(value).toString().equals(value) ? value : null;
        } catch (IllegalArgumentException error) {
            return null;
        }
    }

    private static String rules(String value) {
        if (value == null || value.length() > 100) return null;
        boolean nonblank = false;
        for (int offset = 0; offset < value.length();) {
            int codePoint = value.codePointAt(offset);
            int type = Character.getType(codePoint);
            if (Character.isISOControl(codePoint) || type == Character.SURROGATE || type == Character.FORMAT
                    || type == Character.LINE_SEPARATOR || type == Character.PARAGRAPH_SEPARATOR) return null;
            if (!Character.isWhitespace(codePoint) && !Character.isSpaceChar(codePoint)) nonblank = true;
            offset += Character.charCount(codePoint);
        }
        return nonblank ? value : null;
    }

    static final class State {
        final String requestId;
        String snapshotId;
        String rulesVersion;
        String errorCode;
        boolean selected;

        State(String requestId) {
            this.requestId = requestId;
        }
    }
}
