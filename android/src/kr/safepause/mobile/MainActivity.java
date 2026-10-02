package kr.safepause.mobile;

import android.app.Activity;
import android.content.ActivityNotFoundException;
import android.content.Intent;
import android.content.pm.ApplicationInfo;
import android.content.pm.PackageManager;
import android.content.pm.ResolveInfo;
import android.content.res.Configuration;
import android.database.Cursor;
import android.graphics.Insets;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Looper;
import android.provider.ContactsContract;
import android.speech.tts.TextToSpeech;
import android.speech.tts.UtteranceProgressListener;
import android.speech.tts.Voice;
import android.util.Base64;
import android.util.Log;
import android.view.View;
import android.view.ViewGroup;
import android.widget.FrameLayout;
import android.view.WindowInsets;
import android.webkit.ConsoleMessage;
import android.webkit.JavascriptInterface;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.io.UnsupportedEncodingException;
import java.net.URLDecoder;
import java.text.Collator;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.Callable;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;
import java.util.regex.Pattern;

/**
 * SafePause 안드로이드 셸.
 *
 * <p>화면(HTML·JS)과 AI 엔진(Pyodide 파이썬·scikit-learn)은 모두 APK의 assets/www에 들어 있다.
 * WebView가 https://app.safepause.local/ 로 요청하면 {@link #shouldInterceptRequest}가 assets에서
 * 꺼내 준다. 그 밖의 주소는 모두 403으로 막는다. 앱은 권한을 하나도 요청하지 않는다(INTERNET도 없음).
 * 그래서 기기 밖으로 나가는 통로가 운영체제 수준에서 없다.</p>
 *
 * <p>JS 다리(window.SafePauseNative): 기기 안 음성(TTS) 읽기와 끝남 알림, 파일 저장(시스템 저장 창),
 * 문자·메일 앱과 전화 다이얼 화면 열기(sms·smsto·mailto·tel만), 연락처 한 건 고르기(시스템 선택 창),
 * 홈 화면 앱 목록과 고른 앱 열기(내 은행 앱 열기).</p>
 *
 * <p>SafePause는 돈을 보내지 않는다. 확인 카드 뒤에 본인이 고른 은행 앱을 열 뿐이고, 이체는 그 앱의
 * 인증·한도 절차로 사람이 직접 한다. 은행 이름·패키지는 코드에 넣지 않는다(설치된 앱 목록에서 본인이 고름).</p>
 */
public class MainActivity extends Activity {
    static final String HOST = "app.safepause.local";
    static final String ORIGIN = "https://" + HOST;
    static final String START_URL = ORIGIN + "/index.html";
    private static final String TAG = "SafePause";
    private static final int REQ_OPEN_FILE = 41;
    private static final int REQ_SAVE_FILE = 42;
    private static final int REQ_PICK_PHONE = 43;
    private static final int REQ_PICK_EMAIL = 44;
    private static final int MAX_EXTERNAL_URI = 8000;
    // 앱 열기를 UI 스레드에 맡기고 결과를 기다리는 시간(넘으면 아직 시작 전인 열기는 취소하고 false)
    private static final long UI_WAIT_MS = 2000;
    private static final int MAX_APP_LABEL = 80;
    // 패키지 이름 꼴(영문·숫자·밑줄·점). 실제로 열 수 있는지는 홈 화면 앱 조회로 다시 확인한다.
    private static final Pattern PACKAGE_NAME = Pattern.compile("[A-Za-z0-9_]+(\\.[A-Za-z0-9_]+)*");
    // 앱 밖으로 넘길 수 있는 주소 종류(문자·메일·다이얼 화면). 그 밖은 모두 막는다.
    static final Set<String> EXTERNAL_SCHEMES =
            Collections.unmodifiableSet(new HashSet<>(Arrays.asList("sms", "smsto", "mailto", "tel")));
    private static final Map<String, String> MIME;

    static {
        Map<String, String> m = new HashMap<>();
        m.put("html", "text/html");
        m.put("js", "text/javascript");
        m.put("mjs", "text/javascript");
        m.put("css", "text/css");
        m.put("json", "application/json");
        m.put("wasm", "application/wasm");
        m.put("svg", "image/svg+xml");
        m.put("png", "image/png");
        m.put("ico", "image/x-icon");
        m.put("zip", "application/zip");
        m.put("whl", "application/zip");
        m.put("txt", "text/plain");
        m.put("csv", "text/csv");
        m.put("md", "text/markdown");
        m.put("woff2", "font/woff2");
        MIME = Collections.unmodifiableMap(m);
    }

    private WebView web;
    private ValueCallback<Uri[]> fileCallback;
    private byte[] pendingSave;
    private String pendingSaveToken;
    private TextToSpeech tts;
    private volatile String ttsState = "pending";   // pending | ready | none
    private final AtomicInteger utteranceSeq = new AtomicInteger();
    private final AtomicReference<String> currentUtterance = new AtomicReference<>();
    private volatile boolean pickPending;
    private boolean debuggable;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        debuggable = (getApplicationInfo().flags & ApplicationInfo.FLAG_DEBUGGABLE) != 0;
        WebView.setWebContentsDebuggingEnabled(debuggable);

        // WebView는 자기 padding을 내용 여백으로 쓰지 않으므로, 감싸는 틀(FrameLayout)에 가장자리 여백을 준다
        FrameLayout root = new FrameLayout(this);
        web = new WebView(this);
        web.setId(View.generateViewId());
        root.addView(web, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        setContentView(root);
        applyInsets(root);

        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setAllowFileAccess(false);
        s.setAllowContentAccess(false);
        s.setGeolocationEnabled(false);
        s.setSupportMultipleWindows(false);
        s.setJavaScriptCanOpenWindowsAutomatically(false);
        s.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        s.setMediaPlaybackRequiresUserGesture(true);
        s.setTextZoom(textZoom(getResources().getConfiguration()));
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            s.setSafeBrowsingEnabled(false);   // 안전 탐색 조회(외부 서버)도 쓰지 않는다: 앱 안 주소만 연다
        }

        web.setWebViewClient(new LocalOnlyClient());
        web.setWebChromeClient(new Chrome());
        web.addJavascriptInterface(new NativeBridge(), "SafePauseNative");

        tts = new TextToSpeech(getApplicationContext(), this::onTtsInit);

        if (savedInstanceState != null) {
            web.restoreState(savedInstanceState);
        } else {
            web.loadUrl(START_URL);
        }
    }

    // ---- 화면 가장자리(상태 표시줄·내비게이션 바·키보드) 여백 ----------------------------
    private void applyInsets(View view) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.R) return;   // API 29 이하는 시스템이 알아서 비켜 준다
        view.setOnApplyWindowInsetsListener((v, insets) -> {
            Insets bars = insets.getInsets(WindowInsets.Type.systemBars()
                    | WindowInsets.Type.displayCutout() | WindowInsets.Type.ime());
            v.setPadding(bars.left, bars.top, bars.right, bars.bottom);
            return WindowInsets.CONSUMED;
        });
    }

    private static int textZoom(Configuration c) {
        // 기기 글자 크기 설정을 그대로 따른다(발달장애인 당사자·고령자의 큰 글씨 설정 존중)
        float scale = c.fontScale <= 0 ? 1f : c.fontScale;
        return Math.max(85, Math.min(200, Math.round(scale * 100)));
    }

    @Override
    public void onConfigurationChanged(Configuration newConfig) {
        super.onConfigurationChanged(newConfig);
        if (web != null) web.getSettings().setTextZoom(textZoom(newConfig));
    }

    // ---- 앱 안 파일만 여는 WebViewClient ------------------------------------------------
    private final class LocalOnlyClient extends WebViewClient {
        @Override
        public WebResourceResponse shouldInterceptRequest(WebView view, WebResourceRequest request) {
            Uri url = request.getUrl();
            if (!"https".equals(url.getScheme()) || !HOST.equals(url.getHost())) {
                return blocked();   // 앱 밖 주소는 한 바이트도 내보내지 않는다
            }
            String path = url.getPath();
            if (path == null || path.isEmpty() || "/".equals(path)) path = "/index.html";
            if (path.contains("..")) return blocked();
            try {
                InputStream in = getAssets().open("www" + path);
                String mime = mimeOf(path);
                Map<String, String> headers = new HashMap<>();
                headers.put("Cache-Control", "no-cache");
                headers.put("Access-Control-Allow-Origin", ORIGIN);
                headers.put("X-Content-Type-Options", "nosniff");
                if (path.endsWith(".html")) {
                    headers.put("Content-Security-Policy", PAGE_CSP);
                }
                String enc = mime.startsWith("text/") || mime.endsWith("json") || mime.endsWith("javascript")
                        ? "utf-8" : null;
                return new WebResourceResponse(mime, enc, 200, "OK", headers, in);
            } catch (IOException e) {
                return new WebResourceResponse("text/plain", "utf-8", 404, "Not Found",
                        Collections.<String, String>emptyMap(), new ByteArrayInputStream(new byte[0]));
            }
        }

        @Override
        public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
            Uri url = request.getUrl();
            String scheme = url.getScheme() == null ? "" : url.getScheme().toLowerCase(Locale.ROOT);
            if (EXTERNAL_SCHEMES.contains(scheme)) {
                openExternalUri(url.toString());   // 문자·메일·다이얼 링크는 그 앱으로 넘긴다
                return true;
            }
            return !(HOST.equals(url.getHost()) && "https".equals(scheme));   // 그 밖의 앱 밖 이동 금지
        }
    }

    // 페이지 CSP: 스크립트·연결은 앱 안에서만. 'wasm-unsafe-eval'은 파이썬(WebAssembly) 실행에 필요하다.
    static final String PAGE_CSP = "default-src 'self'; script-src 'self' 'wasm-unsafe-eval'; "
            + "worker-src 'self'; connect-src 'self'; img-src 'self' data: blob:; style-src 'self'; "
            + "font-src 'self'; object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'";

    private static WebResourceResponse blocked() {
        return new WebResourceResponse("text/plain", "utf-8", 403, "Forbidden",
                Collections.<String, String>emptyMap(), new ByteArrayInputStream(new byte[0]));
    }

    private static String mimeOf(String path) {
        int dot = path.lastIndexOf('.');
        String ext = dot < 0 ? "" : path.substring(dot + 1).toLowerCase(Locale.ROOT);
        String m = MIME.get(ext);
        return m != null ? m : "application/octet-stream";
    }

    // ---- 파일 고르기(CSV 올리기) ----------------------------------------------------------
    private final class Chrome extends WebChromeClient {
        @Override
        public boolean onShowFileChooser(WebView view, ValueCallback<Uri[]> callback,
                                         FileChooserParams params) {
            if (fileCallback != null) fileCallback.onReceiveValue(null);
            fileCallback = callback;
            Intent intent = new Intent(Intent.ACTION_OPEN_DOCUMENT);
            intent.addCategory(Intent.CATEGORY_OPENABLE);
            intent.setType("*/*");
            // 은행·카드사 CSV는 기기마다 MIME가 다르게 붙는다(text/csv, text/comma-separated-values, octet-stream 등)
            intent.putExtra(Intent.EXTRA_MIME_TYPES, new String[]{
                    "text/csv", "text/comma-separated-values", "application/csv", "text/plain",
                    "application/vnd.ms-excel", "application/octet-stream"});
            try {
                startActivityForResult(intent, REQ_OPEN_FILE);
                return true;
            } catch (ActivityNotFoundException e) {
                fileCallback = null;
                return false;
            }
        }

        @Override
        public boolean onConsoleMessage(ConsoleMessage m) {
            if (debuggable) Log.i(TAG, m.messageLevel() + " " + m.message() + " @" + m.lineNumber());
            return true;   // 배포판은 화면 로그(받는 사람·금액이 섞일 수 있음)를 기기 로그에 남기지 않는다
        }
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode == REQ_OPEN_FILE) {
            if (fileCallback == null) return;
            Uri[] result = null;
            if (resultCode == RESULT_OK && data != null && data.getData() != null) {
                result = new Uri[]{data.getData()};
            }
            fileCallback.onReceiveValue(result);
            fileCallback = null;
        } else if (requestCode == REQ_SAVE_FILE) {
            String token = pendingSaveToken;
            byte[] bytes = pendingSave;
            pendingSave = null;
            pendingSaveToken = null;
            boolean ok = false;
            if (resultCode == RESULT_OK && data != null && data.getData() != null && bytes != null) {
                try (OutputStream out = getContentResolver().openOutputStream(data.getData(), "w")) {
                    if (out != null) {
                        out.write(bytes);
                        ok = true;
                    }
                } catch (IOException e) {
                    ok = false;
                }
            }
            notifySave(token, ok ? "saved" : (resultCode == RESULT_OK ? "error" : "cancelled"));
        } else if (requestCode == REQ_PICK_PHONE || requestCode == REQ_PICK_EMAIL) {
            pickPending = false;
            String kind = requestCode == REQ_PICK_PHONE ? "phone" : "email";
            notifyContact(contactResult(kind, resultCode, data));
        }
    }

    private void notifySave(String token, String status) {
        if (token == null) return;
        callJs("window.__safepauseSaveDone && window.__safepauseSaveDone("
                + jsString(token) + "," + jsString(status) + ")");
    }

    /** 화면 JS를 UI 스레드에서 부른다(다리 함수·TTS 콜백은 다른 스레드에서 온다). */
    private void callJs(String js) {
        runOnUiThread(() -> {
            if (web != null) web.evaluateJavascript(js, null);
        });
    }

    // ---- 문자·메일 앱, 전화 다이얼 화면 열기 ------------------------------------------------
    /**
     * sms:·smsto:·mailto:·tel: 주소만 앱 밖으로 넘긴다. 열 앱이 있으면 true를 돌려주고 UI 스레드에서 연다.
     * 보내기·걸기는 하지 않는다(문자·메일 앱과 다이얼 화면에서 사람이 직접 누른다).
     */
    boolean openExternalUri(String uri) {
        final Intent intent;
        try {
            intent = externalIntent(uri);
        } catch (RuntimeException e) {
            return false;
        }
        if (intent == null || isFinishing() || !canResolve(intent)) return false;
        runOnUiThread(() -> {
            try {
                startActivity(intent);
            } catch (ActivityNotFoundException | SecurityException e) {
                if (debuggable) Log.w(TAG, "외부 앱 열기 실패: " + e.getClass().getSimpleName());
            }
        });
        return true;
    }

    static Intent externalIntent(String uri) {
        if (uri == null || uri.length() > MAX_EXTERNAL_URI) return null;
        int colon = uri.indexOf(':');
        if (colon <= 0) return null;
        String scheme = uri.substring(0, colon).trim().toLowerCase(Locale.ROOT);
        if (!EXTERNAL_SCHEMES.contains(scheme)) return null;
        String rest = uri.substring(colon + 1);
        String query = "";
        int q = rest.indexOf('?');
        if (q >= 0) {
            query = rest.substring(q + 1);
            rest = rest.substring(0, q);
        }
        if (rest.startsWith("//")) rest = rest.substring(2);   // sms://번호 꼴도 받는다
        String target = Uri.decode(rest).trim();
        Map<String, String> params = parseQuery(query);
        switch (scheme) {
            case "sms":
            case "smsto": {
                // 받는 사람 번호들(쉼표·세미콜론으로 여럿)만 주소에 남기고 글은 sms_body로 넘긴다
                Intent i = new Intent(Intent.ACTION_SENDTO, Uri.parse(scheme + ":" + Uri.encode(target, "+,;")));
                String body = params.get("body");
                if (body != null && !body.isEmpty()) i.putExtra("sms_body", body);
                return i;
            }
            case "mailto": {
                Intent i = new Intent(Intent.ACTION_SENDTO, Uri.parse("mailto:" + Uri.encode(target, "@,+")));
                String subject = params.get("subject");
                String body = params.get("body");
                if (subject != null && !subject.isEmpty()) i.putExtra(Intent.EXTRA_SUBJECT, subject);
                if (body != null && !body.isEmpty()) i.putExtra(Intent.EXTRA_TEXT, body);
                return i;
            }
            case "tel":
                // 전화는 걸지 않고 번호를 채운 다이얼 화면만 연다(CALL_PHONE 권한 없음)
                return new Intent(Intent.ACTION_DIAL, Uri.parse("tel:" + Uri.encode(target, "+,;")));
            default:
                return null;
        }
    }

    /** ?a=1&b=2 꼴의 쿼리를 푼다. 같은 이름은 처음 것만 쓴다. */
    static Map<String, String> parseQuery(String query) {
        Map<String, String> out = new HashMap<>();
        if (query == null || query.isEmpty()) return out;
        int hash = query.indexOf('#');
        if (hash >= 0) query = query.substring(0, hash);
        for (String pair : query.split("&")) {
            if (pair.isEmpty()) continue;
            int eq = pair.indexOf('=');
            String key = urlDecode(eq < 0 ? pair : pair.substring(0, eq)).trim().toLowerCase(Locale.ROOT);
            String value = eq < 0 ? "" : urlDecode(pair.substring(eq + 1));
            if (!key.isEmpty() && !out.containsKey(key)) out.put(key, value);
        }
        return out;
    }

    private static String urlDecode(String s) {
        try {
            return URLDecoder.decode(s, "UTF-8");   // encodeURIComponent(%20)·URLSearchParams(+) 둘 다 푼다
        } catch (UnsupportedEncodingException | IllegalArgumentException e) {
            return Uri.decode(s);   // 잘못된 % 표기는 너그럽게
        }
    }

    private boolean canResolve(Intent intent) {
        try {
            return intent.resolveActivity(getPackageManager()) != null;
        } catch (RuntimeException e) {
            return false;
        }
    }

    // ---- 연락처 한 건 고르기(권한 없이 시스템 선택 창) -----------------------------------------
    private static Intent pickIntent(String kind) {
        Intent i = new Intent(Intent.ACTION_PICK);
        if ("phone".equals(kind)) {
            i.setDataAndType(ContactsContract.CommonDataKinds.Phone.CONTENT_URI,
                    ContactsContract.CommonDataKinds.Phone.CONTENT_TYPE);
        } else if ("email".equals(kind)) {
            i.setDataAndType(ContactsContract.CommonDataKinds.Email.CONTENT_URI,
                    ContactsContract.CommonDataKinds.Email.CONTENT_TYPE);
        } else {
            return null;
        }
        return i;
    }

    boolean startPickContact(String kind) {
        final String k = kind == null ? "" : kind.trim().toLowerCase(Locale.ROOT);
        final Intent intent = pickIntent(k);
        if (intent == null || pickPending || isFinishing() || !canResolve(intent)) return false;
        pickPending = true;
        runOnUiThread(() -> {
            try {
                startActivityForResult(intent, "phone".equals(k) ? REQ_PICK_PHONE : REQ_PICK_EMAIL);
            } catch (ActivityNotFoundException | SecurityException e) {
                pickPending = false;
                notifyContact(contactError(k, "no_app"));
            }
        });
        return true;
    }

    private JSONObject contactResult(String kind, int resultCode, Intent data) {
        Uri uri = data == null ? null : data.getData();
        if (resultCode != RESULT_OK || uri == null) {
            JSONObject o = new JSONObject();
            try {
                o.put("kind", kind);
                o.put("cancelled", true);
            } catch (JSONException e) {
                return contactError(kind, "json");
            }
            return o;
        }
        // 선택 창이 준 주소는 그 한 건만 읽을 수 있게 허락돼 있다(READ_CONTACTS 없이)
        String valueCol = "phone".equals(kind)
                ? ContactsContract.CommonDataKinds.Phone.NUMBER
                : ContactsContract.CommonDataKinds.Email.ADDRESS;
        String[] projection = {ContactsContract.Contacts.DISPLAY_NAME, valueCol};
        try (Cursor c = getContentResolver().query(uri, projection, null, null, null)) {
            if (c == null || !c.moveToFirst()) return contactError(kind, "not_found");
            int ni = c.getColumnIndex(ContactsContract.Contacts.DISPLAY_NAME);
            int vi = c.getColumnIndex(valueCol);
            String name = ni < 0 || c.isNull(ni) ? "" : c.getString(ni).trim();
            String value = vi < 0 || c.isNull(vi) ? "" : c.getString(vi).trim();
            if (value.isEmpty()) return contactError(kind, "empty");
            JSONObject o = new JSONObject();
            o.put("kind", kind);
            o.put("name", name);
            o.put("value", value);
            return o;
        } catch (SecurityException | IllegalArgumentException | IllegalStateException | JSONException e) {
            return contactError(kind, "read_failed");
        }
    }

    private static JSONObject contactError(String kind, String code) {
        JSONObject o = new JSONObject();
        try {
            o.put("kind", kind);
            o.put("error", code);
        } catch (JSONException ignored) {
            // 문자열 두 개라 실패하지 않는다
        }
        return o;
    }

    private void notifyContact(JSONObject result) {
        callJs("window.__safepauseContactPicked && window.__safepauseContactPicked(" + jsonForJs(result) + ")");
    }

    /** JSONObject 글을 JS 식으로 넣을 때 줄 구분 문자(U+2028·U+2029)도 이스케이프한다. */
    private static String jsonForJs(JSONObject o) {
        return o.toString().replace("\u2028", "\\u2028").replace("\u2029", "\\u2029");
    }

    private static String jsString(String s) {
        StringBuilder b = new StringBuilder("\"");
        for (char c : s.toCharArray()) {
            if (c == '"' || c == '\\') b.append('\\').append(c);
            else if (c < 0x20 || c == 0x2028 || c == 0x2029) b.append(String.format(Locale.ROOT, "\\u%04x", (int) c));
            else b.append(c);
        }
        return b.append('"').toString();
    }

    // ---- 홈 화면 앱 목록·열기(내 은행 앱) ----------------------------------------------------
    // 패키지 가시성(안드로이드 11+): 매니페스트 queries의 MAIN·LAUNCHER intent로 홈 화면에 아이콘이 있는
    // 앱만 보인다. QUERY_ALL_PACKAGES 권한은 쓰지 않는다. 목록은 화면(WebView)에만 넘기고 기기 밖으로 나가지 않는다.

    /** 홈 화면 앱 한 개: 패키지 이름과 홈 화면에 보이는 이름. */
    static final class AppEntry {
        final String pkg;
        final String label;

        AppEntry(String pkg, String label) {
            this.pkg = pkg;
            this.label = label;
        }
    }

    private static Intent launcherIntent() {
        Intent i = new Intent(Intent.ACTION_MAIN);
        i.addCategory(Intent.CATEGORY_LAUNCHER);
        return i;
    }

    @SuppressWarnings("deprecation")
    private static List<ResolveInfo> queryActivities(PackageManager pm, Intent intent) {
        List<ResolveInfo> r = Build.VERSION.SDK_INT >= 33
                ? pm.queryIntentActivities(intent, PackageManager.ResolveInfoFlags.of(0))
                : pm.queryIntentActivities(intent, 0);
        return r == null ? Collections.<ResolveInfo>emptyList() : r;
    }

    /**
     * 실행할 수 있는 앱(MAIN·LAUNCHER) 목록. 자기 앱은 빼고, 같은 패키지는 한 번만 넣는다.
     * 한 패키지에 홈 화면 아이콘이 여럿이면 앱 이름(application label)을, 하나면 그 아이콘 이름을 쓴다.
     * 순서는 {@link #sortApps}(한글 가나다 → 영문 알파벳 → 그 밖).
     */
    List<AppEntry> launcherApps() {
        PackageManager pm = getPackageManager();
        String self = getPackageName();
        Map<String, ResolveInfo> first = new LinkedHashMap<>();
        Set<String> several = new HashSet<>();
        for (ResolveInfo ri : queryActivities(pm, launcherIntent())) {
            if (ri == null || ri.activityInfo == null) continue;
            String pkg = ri.activityInfo.packageName;
            if (pkg == null || pkg.isEmpty() || pkg.equals(self)) continue;
            if (first.containsKey(pkg)) several.add(pkg);
            else first.put(pkg, ri);
        }
        List<AppEntry> apps = new ArrayList<>(first.size());
        for (Map.Entry<String, ResolveInfo> e : first.entrySet()) {
            String pkg = e.getKey();
            ResolveInfo ri = e.getValue();
            CharSequence raw;
            try {
                raw = several.contains(pkg) && ri.activityInfo.applicationInfo != null
                        ? ri.activityInfo.applicationInfo.loadLabel(pm)
                        : ri.loadLabel(pm);
            } catch (RuntimeException ex) {
                raw = null;
            }
            apps.add(new AppEntry(pkg, cleanLabel(raw, pkg)));
        }
        sortApps(apps);
        return apps;
    }

    /** 홈 화면 이름을 한 줄로 다듬는다: 줄바꿈·연속 공백은 공백 하나, 보이지 않는 서식 문자는 뺀다. 비면 패키지 이름. */
    static String cleanLabel(CharSequence raw, String pkg) {
        String s = raw == null ? "" : raw.toString();
        StringBuilder b = new StringBuilder(s.length());
        boolean space = false;
        for (int i = 0; i < s.length(); ) {
            int cp = s.codePointAt(i);
            i += Character.charCount(cp);
            int type = Character.getType(cp);
            if (type == Character.FORMAT) continue;   // 방향 표시·폭 없는 문자
            if (Character.isWhitespace(cp) || Character.isSpaceChar(cp) || Character.isISOControl(cp)) {
                space = b.length() > 0;
                continue;
            }
            if (space) b.append(' ');
            space = false;
            b.appendCodePoint(cp);
        }
        String out = b.toString();
        if (out.codePointCount(0, out.length()) > MAX_APP_LABEL) {
            out = out.substring(0, out.offsetByCodePoints(0, MAX_APP_LABEL));
        }
        return out.isEmpty() ? (pkg == null ? "" : pkg) : out;
    }

    /** 이름 첫 글자로 나눈 묶음: 한글 0, 영문 1, 그 밖(숫자·기호·다른 글자) 2. */
    static int scriptGroup(String label) {
        if (label == null || label.isEmpty()) return 2;
        Character.UnicodeScript s = Character.UnicodeScript.of(label.codePointAt(0));
        if (s == Character.UnicodeScript.HANGUL) return 0;
        if (s == Character.UnicodeScript.LATIN) return 1;
        return 2;
    }

    /** 한글 가나다순 → 영문 알파벳순(대소문자 구분 없이) → 그 밖. 이름이 같으면 패키지 이름순. */
    static void sortApps(List<AppEntry> apps) {
        final Collator collator = Collator.getInstance(Locale.KOREAN);
        collator.setStrength(Collator.SECONDARY);   // 대소문자 차이는 순서에 쓰지 않는다
        Collections.sort(apps, (a, b) -> {
            int c = Integer.compare(scriptGroup(a.label), scriptGroup(b.label));
            if (c == 0) c = collator.compare(a.label, b.label);
            if (c == 0) c = a.label.compareTo(b.label);
            if (c == 0) c = a.pkg.compareTo(b.pkg);
            return c;
        });
    }

    /** [{"package": "...", "label": "..."}, ...] JSON 글. 실패하면 "[]". */
    String launcherAppsJson() {
        try {
            JSONArray arr = new JSONArray();
            for (AppEntry a : launcherApps()) {
                JSONObject o = new JSONObject();
                o.put("package", a.pkg);
                o.put("label", a.label);
                arr.put(o);
            }
            return arr.toString();
        } catch (JSONException | RuntimeException e) {
            if (debuggable) Log.w(TAG, "앱 목록 읽기 실패: " + e.getClass().getSimpleName());
            return "[]";
        }
    }

    /** 홈 화면 앱 목록(launcherApps)에 있는 패키지인가. 같은 MAIN·LAUNCHER 조회를 그 패키지로 좁혀 확인한다. */
    private boolean isLauncherApp(String pkg) {
        if (pkg.equals(getPackageName())) return false;
        Intent i = launcherIntent();
        i.setPackage(pkg);
        for (ResolveInfo ri : queryActivities(getPackageManager(), i)) {
            if (ri != null && ri.activityInfo != null && pkg.equals(ri.activityInfo.packageName)) return true;
        }
        return false;
    }

    /**
     * 홈 화면 앱 목록에 있는 앱을 연다(getLaunchIntentForPackage + FLAG_ACTIVITY_NEW_TASK).
     * 열기는 UI 스레드에서 하고 그 결과(시작했으면 true)를 돌려준다. 목록에 없거나 예외가 나면 false.
     */
    boolean openLauncherApp(String pkg) {
        final String p = pkg == null ? "" : pkg.trim();
        if (p.isEmpty() || p.length() > 255 || !PACKAGE_NAME.matcher(p).matches() || isFinishing()) return false;
        try {
            if (!isLauncherApp(p)) return false;
            final Intent intent = getPackageManager().getLaunchIntentForPackage(p);
            if (intent == null) return false;
            intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            return runOnUiForResult(() -> {
                if (isFinishing()) return false;
                startActivity(intent);
                return true;
            });
        } catch (RuntimeException e) {
            if (debuggable) Log.w(TAG, "앱 열기 실패: " + e.getClass().getSimpleName());
            return false;
        }
    }

    /**
     * task를 UI 스레드에서 돌리고 결과를 기다린다(다리 함수는 JavaBridge 스레드에서 온다).
     * UI_WAIT_MS 안에 시작도 못 했으면 취소하고 false. 이미 시작했으면 끝날 때까지 한 번 더 기다리고,
     * 그래도 안 끝나면 열기를 요청한 것으로 보고 true. task의 예외는 false.
     */
    private boolean runOnUiForResult(final Callable<Boolean> task) {
        if (Looper.myLooper() == Looper.getMainLooper()) return callSafely(task);
        final AtomicInteger state = new AtomicInteger(0);   // 0 기다림, 1 시작함, 2 취소함
        final AtomicBoolean result = new AtomicBoolean(false);
        final CountDownLatch done = new CountDownLatch(1);
        runOnUiThread(() -> {
            if (!state.compareAndSet(0, 1)) return;   // 기다리다 그만둔 열기는 하지 않는다
            try {
                result.set(callSafely(task));
            } finally {
                done.countDown();
            }
        });
        boolean interrupted = false;
        try {
            if (done.await(UI_WAIT_MS, TimeUnit.MILLISECONDS)) return result.get();
            if (state.compareAndSet(0, 2)) return false;
            return !done.await(UI_WAIT_MS, TimeUnit.MILLISECONDS) || result.get();
        } catch (InterruptedException e) {
            interrupted = true;
            return !state.compareAndSet(0, 2) && (done.getCount() > 0 || result.get());
        } finally {
            if (interrupted) Thread.currentThread().interrupt();
        }
    }

    private static boolean callSafely(Callable<Boolean> task) {
        try {
            return Boolean.TRUE.equals(task.call());
        } catch (Exception e) {   // ActivityNotFoundException·SecurityException 등
            return false;
        }
    }

    // ---- 기기 안 음성(TTS) -----------------------------------------------------------------
    private void onTtsInit(int status) {
        if (status != TextToSpeech.SUCCESS || tts == null) {
            ttsState = "none";
            return;
        }
        Voice pick = null;
        try {
            for (Voice v : tts.getVoices()) {
                if (v == null || v.getLocale() == null) continue;
                if (!"ko".equals(v.getLocale().getLanguage())) continue;
                // 인터넷으로 글을 보내는 음성은 쓰지 않는다(받는 사람·금액이 기기 밖으로 나가지 않게)
                if (v.isNetworkConnectionRequired()) continue;
                if (v.getFeatures() != null
                        && v.getFeatures().contains(TextToSpeech.Engine.KEY_FEATURE_NETWORK_SYNTHESIS)) continue;
                if (pick == null || v.getQuality() > pick.getQuality()) pick = v;
            }
        } catch (RuntimeException e) {
            pick = null;
        }
        if (pick == null) {
            ttsState = "none";
            return;
        }
        tts.setVoice(pick);
        tts.setSpeechRate(0.9f);
        tts.setOnUtteranceProgressListener(new SpeechListener());
        ttsState = "ready";
    }

    /** 읽기가 끝나거나(다 읽음·오류·멈춤) 하면 화면의 소리 버튼을 원래대로 돌리게 알린다. */
    private final class SpeechListener extends UtteranceProgressListener {
        @Override
        public void onStart(String utteranceId) {
            // 시작은 speak()가 true를 돌려줄 때 화면이 이미 안다
        }

        @Override
        public void onDone(String utteranceId) {
            speechEnded(utteranceId, "done");
        }

        @Override
        @SuppressWarnings("deprecation")
        public void onError(String utteranceId) {
            speechEnded(utteranceId, "error");
        }

        @Override
        public void onStop(String utteranceId, boolean interrupted) {
            speechEnded(utteranceId, "stopped");
        }
    }

    private void speechEnded(String utteranceId, String reason) {
        // 새 읽기에 밀려 끝난 옛 읽기는 알리지 않는다(지금 읽는 것만)
        if (utteranceId == null || !currentUtterance.compareAndSet(utteranceId, null)) return;
        notifySpeechDone(reason);
    }

    private void notifySpeechDone(String reason) {
        callJs("window.__safepauseSpeechDone && window.__safepauseSpeechDone(" + jsString(reason) + ")");
    }

    /** 읽기를 멈추고, 읽던 것이 있었으면 끝남을 바로 알린다(엔진에 따라 onStop이 오지 않을 수 있음). */
    private void stopSpeech() {
        String id = currentUtterance.getAndSet(null);
        if (tts != null) tts.stop();
        if (id != null) notifySpeechDone("stopped");
    }

    private final class NativeBridge {
        @JavascriptInterface
        public String ttsStatus() {
            return ttsState;
        }

        /** 읽기 시작. 끝나면(다 읽음·오류·멈춤) window.__safepauseSpeechDone(reason)을 부른다. */
        @JavascriptInterface
        public boolean speak(String text) {
            TextToSpeech engine = tts;
            if (!"ready".equals(ttsState) || engine == null || text == null) return false;
            Bundle p = new Bundle();
            p.putString(TextToSpeech.Engine.KEY_FEATURE_EMBEDDED_SYNTHESIS, "true");
            String t = text.length() > 3000 ? text.substring(0, 3000) : text;
            String id = "safepause-" + utteranceSeq.incrementAndGet();
            currentUtterance.set(id);   // 먼저 바꿔 둬야 QUEUE_FLUSH로 밀린 옛 읽기의 onStop을 거른다
            boolean ok = engine.speak(t, TextToSpeech.QUEUE_FLUSH, p, id) == TextToSpeech.SUCCESS;
            if (!ok) currentUtterance.compareAndSet(id, null);
            return ok;
        }

        @JavascriptInterface
        public void stopSpeaking() {
            stopSpeech();
        }

        /** sms:·smsto:·mailto:·tel: 주소로 문자·메일 앱이나 다이얼 화면을 연다. 열 앱이 없거나 다른 주소면 false. */
        @JavascriptInterface
        public boolean openExternal(String uri) {
            return openExternalUri(uri);
        }

        /**
         * kind는 phone·email. 시스템 연락처 선택 창을 연다(열었으면 true).
         * 결과는 window.__safepauseContactPicked({kind, name, value} | {kind, cancelled} | {kind, error})로 알린다.
         */
        @JavascriptInterface
        public boolean pickContact(String kind) {
            return startPickContact(kind);
        }

        /**
         * 홈 화면에 아이콘이 있는(실행할 수 있는) 앱 목록. 자기 앱은 빠진다.
         * JSON 배열 글 [{"package": "패키지 이름", "label": "홈 화면 이름"}, ...]: 한글 가나다 → 영문 알파벳 → 그 밖 순,
         * 패키지는 한 번씩만. 읽지 못하면 "[]".
         */
        @JavascriptInterface
        public String listApps() {
            return launcherAppsJson();
        }

        /** listApps에 있는 패키지의 앱을 연다. 열기를 시작했으면 true, 목록에 없거나 열지 못하면 false. */
        @JavascriptInterface
        public boolean openApp(String pkg) {
            return openLauncherApp(pkg);
        }

        /** 이 기기에서 쓸 수 있는 기능(JSON 글). */
        @JavascriptInterface
        public String capabilities() {
            JSONObject o = new JSONObject();
            try {
                o.put("external", true);
                o.put("contacts", canResolve(pickIntent("phone")) || canResolve(pickIntent("email")));
                o.put("tts", "ready".equals(ttsState));
                o.put("ttsState", ttsState);
                o.put("sms", canResolve(new Intent(Intent.ACTION_SENDTO, Uri.parse("smsto:"))));
                o.put("email", canResolve(new Intent(Intent.ACTION_SENDTO, Uri.parse("mailto:"))));
                o.put("dial", canResolve(new Intent(Intent.ACTION_DIAL, Uri.parse("tel:"))));
                o.put("apps", true);   // listApps·openApp(내 은행 앱 고르기·열기)
                o.put("version", appVersion());
            } catch (JSONException e) {
                return "{\"external\":true,\"contacts\":true,\"tts\":false,\"apps\":true}";
            }
            return o.toString();
        }

        /** 시스템 '저장' 창을 열어 파일을 저장한다. 결과는 window.__safepauseSaveDone(token, status)로 알린다. */
        @JavascriptInterface
        public boolean saveFile(String token, String filename, String mime, String base64) {
            if (filename == null || base64 == null || base64.length() > 30_000_000) return false;
            final byte[] bytes;
            try {
                bytes = Base64.decode(base64, Base64.DEFAULT);
            } catch (IllegalArgumentException e) {
                return false;
            }
            runOnUiThread(() -> {
                if (pendingSaveToken != null) notifySave(pendingSaveToken, "cancelled");
                pendingSave = bytes;
                pendingSaveToken = token;
                Intent intent = new Intent(Intent.ACTION_CREATE_DOCUMENT);
                intent.addCategory(Intent.CATEGORY_OPENABLE);
                intent.setType(mime == null || mime.isEmpty() ? "application/octet-stream" : mime);
                intent.putExtra(Intent.EXTRA_TITLE, filename.replaceAll("[\\\\/:*?\"<>|]", "_"));
                try {
                    startActivityForResult(intent, REQ_SAVE_FILE);
                } catch (ActivityNotFoundException e) {
                    pendingSave = null;
                    pendingSaveToken = null;
                    notifySave(token, "error");
                }
            });
            return true;
        }

        @JavascriptInterface
        public String platform() {
            return "android " + Build.VERSION.RELEASE + " sdk" + Build.VERSION.SDK_INT;
        }
    }

    private String appVersion() {
        try {
            String v = getPackageManager().getPackageInfo(getPackageName(), 0).versionName;
            return v == null ? "" : v;
        } catch (PackageManager.NameNotFoundException e) {
            return "";
        }
    }

    // ---- 뒤로 가기: 열린 창(카드·시트)을 먼저 닫고, 그다음 앞 화면으로 ---------------------------
    @Override
    @SuppressWarnings("deprecation")
    public void onBackPressed() {
        if (web == null) {
            super.onBackPressed();
            return;
        }
        web.evaluateJavascript("(window.__safepauseBack ? window.__safepauseBack() : false)", value -> {
            if ("true".equals(value)) return;
            if (web.canGoBack()) web.goBack();
            else finish();
        });
    }

    @Override
    protected void onSaveInstanceState(Bundle outState) {
        super.onSaveInstanceState(outState);
        if (web != null) web.saveState(outState);
    }

    @Override
    protected void onPause() {
        super.onPause();
        stopSpeech();   // 화면을 떠나면 읽기를 멈추고 소리 버튼도 원래대로
        if (web != null) web.onPause();
    }

    @Override
    protected void onResume() {
        super.onResume();
        if (web != null) web.onResume();
    }

    @Override
    protected void onDestroy() {
        if (fileCallback != null) {
            fileCallback.onReceiveValue(null);
            fileCallback = null;
        }
        if (tts != null) {
            tts.stop();
            tts.shutdown();
            tts = null;
        }
        if (web != null) {
            web.removeJavascriptInterface("SafePauseNative");
            web.stopLoading();
            if (web.getParent() instanceof ViewGroup) ((ViewGroup) web.getParent()).removeView(web);
            web.destroy();
            web = null;
        }
        super.onDestroy();
    }
}
