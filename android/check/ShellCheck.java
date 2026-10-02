package kr.safepause.mobile;

import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;

/**
 * MainActivity의 안드로이드 API를 쓰지 않는 부분을 PC의 JVM에서 시험한다(에뮬레이터 없이).
 * 실행: python android/check_shell.py --sdk <SDK> --jdk <JDK>
 * (android.jar를 클래스 경로에 두고 MainActivity와 함께 컴파일한다. APK에는 들어가지 않는다.)
 */
public class ShellCheck {
    static int fails = 0;

    static void eq(String what, Object got, Object want) {
        boolean ok = want == null ? got == null : want.equals(got);
        System.out.println((ok ? "ok   " : "FAIL ") + what + " -> " + got + (ok ? "" : "  (want " + want + ")"));
        if (!ok) fails++;
    }

    /** 브라우저 encodeURIComponent와 같은 인코딩(남기는 글자: 영문·숫자·-_.!~*'()). */
    static String encodeURIComponent(String s) {
        StringBuilder b = new StringBuilder();
        for (byte x : s.getBytes(StandardCharsets.UTF_8)) {
            int c = x & 0xFF;
            if ((c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || "-_.!~*'()".indexOf(c) >= 0) {
                b.append((char) c);
            } else {
                b.append('%').append(String.format("%02X", c));
            }
        }
        return b.toString();
    }

    static String repeat(String s, int n) {
        StringBuilder b = new StringBuilder();
        for (int i = 0; i < n; i++) b.append(s);
        return b.toString();
    }

    public static void main(String[] a) {
        speech();
        external();
        labels();
        System.out.println(fails == 0 ? "ALL OK" : ("FAILS " + fails));
        System.exit(fails == 0 ? 0 : 1);
    }

    // AND-01: TTS 끝남 알림의 id는 Binder로 넘어온 새 String이다(참조가 다름)
    static void speech() {
        MainActivity.SpeechTurn t = new MainActivity.SpeechTurn();
        String id = t.begin();
        String fromBinder = new String(id.toCharArray());
        eq("speech: binder id is a different reference", fromBinder != id, true);
        eq("speech: done with equal id (new String) ends it", t.end(fromBinder), true);
        eq("speech: only once", t.end(new String(id.toCharArray())), false);
        eq("speech: not active after done", t.active(), false);

        String first = t.begin();
        String second = t.begin();   // QUEUE_FLUSH로 앞 발화가 밀림
        eq("speech: old utterance's late onStop ignored", t.end(new String(first.toCharArray())), false);
        eq("speech: current still active", t.active(), true);
        eq("speech: current ends", t.end(new String(second.toCharArray())), true);

        String third = t.begin();
        eq("speech: stop clears (had one)", t.clear(), true);
        eq("speech: onStop after stop ignored", t.end(new String(third.toCharArray())), false);
        eq("speech: second stop has none", t.clear(), false);
        eq("speech: null id ignored", t.end(null), false);
        eq("speech: ids are distinct", first.equals(second) || second.equals(third), false);
    }

    // AND-06: 글 길이는 푼 글자 수로 잰다(한글 한 글자 = 주소 9자)
    static void external() {
        String body900 = repeat("가", 900);
        String uri900 = "smsto:01012345678?body=" + encodeURIComponent(body900);
        eq("ext: 900 hangul uri is longer than old 8000 cap", uri900.length() > 8000, true);
        MainActivity.ExternalParts p = MainActivity.splitExternal(uri900);
        eq("ext: 900 hangul sms accepted", p != null, true);
        eq("ext: body decoded to 900 chars", p == null ? -1 : p.params.get("body").length(), 900);
        eq("ext: target kept", p == null ? null : p.rawTarget, "01012345678");

        String body1000 = repeat("한", 1000) ;
        String uri1000 = "smsto:01012345678;01022223333?body=" + encodeURIComponent(body1000);
        MainActivity.ExternalParts p1 = MainActivity.splitExternal(uri1000);
        eq("ext: 1000 hangul sms (screen limit) accepted", p1 != null && p1.params.get("body").equals(body1000), true);

        String mail = "mailto:a@b.kr,c@d.kr?subject=" + encodeURIComponent("[SafePause] 확인해 주세요")
                + "&body=" + encodeURIComponent(repeat("메일 본문 줄\n", 150));
        MainActivity.ExternalParts pm = MainActivity.splitExternal(mail);
        eq("ext: mail accepted", pm != null, true);
        eq("ext: mail subject decoded", pm == null ? null : pm.params.get("subject"), "[SafePause] 확인해 주세요");
        eq("ext: mail body newlines kept", pm == null ? -1 : pm.params.get("body").split("\n", -1).length, 151);

        eq("ext: plus in body is literal (encodeURIComponent %2B)",
                MainActivity.splitExternal("sms:1?body=" + encodeURIComponent("1+1 a b")).params.get("body"), "1+1 a b");
        eq("ext: body over 10000 chars refused",
                MainActivity.splitExternal("smsto:1?body=" + repeat("a", MainActivity.MAX_EXTERNAL_TEXT + 1)), null);
        eq("ext: subject over 500 chars refused",
                MainActivity.splitExternal("mailto:a@b.kr?subject=" + repeat("a", MainActivity.MAX_EXTERNAL_SUBJECT + 1)), null);
        eq("ext: whole uri over cap refused",
                MainActivity.splitExternal("smsto:1?x=" + repeat("a", MainActivity.MAX_EXTERNAL_URI)), null);
        eq("ext: http refused", MainActivity.splitExternal("https://example.com/?body=1"), null);
        eq("ext: intent refused", MainActivity.splitExternal("intent:#Intent;end"), null);
        eq("ext: javascript refused", MainActivity.splitExternal("javascript:alert(1)"), null);
        eq("ext: null refused", MainActivity.splitExternal(null), null);
        eq("ext: no scheme refused", MainActivity.splitExternal(":1"), null);
        eq("ext: sms:// form", MainActivity.splitExternal("sms://010?body=x").rawTarget, "010");
        eq("ext: tel scheme case-insensitive", MainActivity.splitExternal("TEL:1644").scheme, "tel");
    }

    // 앞서 쓰던 HelperCheck 사례(앱 목록 이름·순서)
    static void labels() {
        eq("clean newline", MainActivity.cleanLabel("내 \n 앱\t이름", "p.k"), "내 앱 이름");
        eq("clean bidi/zwsp", MainActivity.cleanLabel("‎가​나 다", "p.k"), "가나 다");
        eq("clean empty->pkg", MainActivity.cleanLabel("  ‎ ", "com.ex.a"), "com.ex.a");
        eq("clean null->pkg", MainActivity.cleanLabel(null, "com.ex.a"), "com.ex.a");
        eq("clean cap 80", MainActivity.cleanLabel(repeat("가", 100), "p").length(), 80);
        String e = MainActivity.cleanLabel(repeat("😀", 100), "p");
        eq("clean cap surrogate safe", e.codePointCount(0, e.length()) + "/" + Character.isHighSurrogate(e.charAt(e.length() - 1)), "80/false");
        eq("group hangul", MainActivity.scriptGroup("하늘"), 0);
        eq("group jamo", MainActivity.scriptGroup("ㅎㅎ"), 0);
        eq("group latin", MainActivity.scriptGroup("alpha"), 1);
        eq("group fullwidth latin", MainActivity.scriptGroup("Ａbc"), 1);
        eq("group digit", MainActivity.scriptGroup("1st"), 2);
        eq("group empty", MainActivity.scriptGroup(""), 2);
        List<MainActivity.AppEntry> l = new ArrayList<>();
        String[][] in = {{"z.p", "zeta"}, {"b.p", "Beta"}, {"h.p", "하나 앱"}, {"g.p", "가방"}, {"n.p", "1번 앱"},
                {"a2.p", "alpha"}, {"a1.p", "Alpha"}, {"a3.p", "alpha"}, {"d.p", "다람쥐"}, {"x.p", "日本"}};
        for (String[] r : in) l.add(new MainActivity.AppEntry(r[0], r[1]));
        MainActivity.sortApps(l);
        StringBuilder order = new StringBuilder();
        for (MainActivity.AppEntry x : l) order.append(x.label).append('(').append(x.pkg).append(") ");
        eq("sort order", order.toString().trim(),
                "가방(g.p) 다람쥐(d.p) 하나 앱(h.p) Alpha(a1.p) alpha(a2.p) alpha(a3.p) Beta(b.p) zeta(z.p) 1번 앱(n.p) 日本(x.p)");
    }
}
