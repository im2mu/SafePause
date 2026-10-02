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
import android.graphics.drawable.ColorDrawable;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Looper;
import android.os.SystemClock;
import android.provider.ContactsContract;
import android.provider.DocumentsContract;
import android.speech.tts.TextToSpeech;
import android.speech.tts.UtteranceProgressListener;
import android.speech.tts.Voice;
import android.util.Base64;
import android.util.Log;
import android.view.View;
import android.view.ViewGroup;
import android.view.Window;
import android.view.WindowInsetsController;
import android.widget.FrameLayout;
import android.widget.Toast;
import android.view.WindowInsets;
import android.webkit.ConsoleMessage;
import android.webkit.JavascriptInterface;
import android.webkit.RenderProcessGoneDetail;
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
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
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
 * 홈 화면 앱 목록과 고른 앱 열기(내 은행 앱 열기), 화면 모드(밝게·어둡게)에 맞춘 막대 색.</p>
 *
 * <p>렌더러(화면 프로세스)가 죽으면 새 WebView로 다시 연다(onRenderProcessGone). 연락처·파일·저장 창이 열린 사이
 * 화면이나 앱이 다시 만들어지면 그 결과는 토스트로 알리고, 저장할 내용은 cacheDir에 잠시 두어 빈 파일을 남기지 않는다.</p>
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
    // 문자·메일 주소 한도. 글은 주소가 아니라 Intent extra(sms_body·EXTRA_TEXT)로 넘기므로 한도는 푼 글자 수로 잰다.
    // 한글 한 글자는 encodeURIComponent로 9자가 되므로 주소 전체 한도는 넉넉히 둔다(화면의 글 한도는 1,000자).
    static final int MAX_EXTERNAL_URI = 100_000;
    static final int MAX_EXTERNAL_TEXT = 10_000;     // 문자·메일 본문(푼 글자 수)
    static final int MAX_EXTERNAL_SUBJECT = 500;     // 메일 제목
    static final int MAX_EXTERNAL_TARGET = 4_000;    // 받는 사람 번호·주소 묶음(최대 10명)
    // 렌더러(화면 프로세스)가 죽었을 때 다시 띄우는 횟수 한도: 이 시간 안에 이보다 많이 죽으면 앱을 닫는다
    private static final long RENDERER_WINDOW_MS = 60_000;
    private static final int MAX_RENDERER_RESTARTS = 3;
    // 저장 창이 열린 사이 앱이 다시 만들어져도(메모리 회수 등) 저장할 내용을 잃지 않게 cacheDir에 잠시 둔다
    private static final String SAVE_DIR = "pending-save";
    private static final Pattern SAVE_NAME = Pattern.compile("save-[0-9a-f]{1,32}\\.bin");
    private static final String STATE_SAVE_FILE = "safepause.saveFile";
    private static final String STATE_SAVE_TOKEN = "safepause.saveToken";
    private static final String STATE_THEME = "safepause.themeMode";
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

    private FrameLayout root;
    private WebView web;
    // 지금 페이지의 번호. 새 페이지를 열 때마다(처음·렌더러 다시 띄우기·액티비티 다시 만들기) 1씩 늘린다.
    // 연락처·파일·저장 창의 결과가 그 창을 연 페이지가 아닌 새 페이지에 오면 화면 대신 토스트로 알린다.
    private int pageGen;
    private ValueCallback<Uri[]> fileCallback;
    // 저장: 열린 저장 창 하나만. 내용은 cacheDir 파일(pendingSaveFile)에 두고 결과가 오면 지운다.
    private final AtomicBoolean savePending = new AtomicBoolean();
    private String pendingSaveToken;
    private File pendingSaveFile;
    private int saveGen = -1;
    private TextToSpeech tts;
    private volatile String ttsState = "pending";   // pending | ready | none
    private final SpeechTurn speech = new SpeechTurn();
    // 연락처: 열린 선택 창 하나만. 두 번째 요청은 false(첫 창의 결과는 그대로 __safepauseContactPicked로 온다).
    private final AtomicBoolean pickPending = new AtomicBoolean();
    private int pickGen = -1;
    private String themeMode = "auto";   // 화면 설정(auto | light | dark), setThemeMode로 바뀐다
    private long rendererWindowStart;
    private int rendererRestarts;
    private boolean resumed;
    private boolean reopenOnResume;   // 뒤에 있는 동안 렌더러가 죽었다: 앞으로 돌아오면 다시 연다
    private boolean debuggable;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        // 런처 아이콘으로 다시 들어올 때 같은 작업 위에 새 화면이 하나 더 생기면(처음에 다른 경로로 열린 경우)
        // 그 새 화면은 닫는다. 작업 맨 위에 있던 연락처·파일·저장 창이나 앞 화면이 그대로 보인다.
        if (!isTaskRoot() && isLauncherIntent(getIntent())) {
            finish();
            return;
        }
        debuggable = (getApplicationInfo().flags & ApplicationInfo.FLAG_DEBUGGABLE) != 0;
        WebView.setWebContentsDebuggingEnabled(debuggable);

        // WebView는 자기 padding을 내용 여백으로 쓰지 않으므로, 감싸는 틀(FrameLayout)에 가장자리 여백을 준다
        root = new FrameLayout(this);
        setContentView(root);
        applyInsets(root);

        if (savedInstanceState != null) restoreNativeState(savedInstanceState);
        cleanSaveCache();
        applySystemBars();

        tts = new TextToSpeech(getApplicationContext(), this::onTtsInit);

        web = createWebView();
        root.addView(web, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        pageGen++;
        if (savedInstanceState == null || web.restoreState(savedInstanceState) == null) {
            web.loadUrl(START_URL);
        }
    }

    private static boolean isLauncherIntent(Intent i) {
        return i != null && Intent.ACTION_MAIN.equals(i.getAction()) && i.hasCategory(Intent.CATEGORY_LAUNCHER);
    }

    /** 같은 설정·다리(SafePauseNative)를 가진 WebView를 만든다. 처음과 렌더러를 다시 띄울 때 쓴다. */
    private WebView createWebView() {
        WebView w = new WebView(this);
        w.setId(View.generateViewId());
        WebSettings s = w.getSettings();
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
        w.setWebViewClient(new LocalOnlyClient());
        w.setWebChromeClient(new Chrome());
        w.addJavascriptInterface(new NativeBridge(), "SafePauseNative");
        return w;
    }

    private static void destroyWebView(WebView w) {
        if (w == null) return;
        try {
            w.removeJavascriptInterface("SafePauseNative");
            w.stopLoading();
        } catch (RuntimeException ignored) {
            // 렌더러가 이미 죽은 WebView도 떼어 내고 없애기만 하면 된다
        }
        if (w.getParent() instanceof ViewGroup) ((ViewGroup) w.getParent()).removeView(w);
        w.destroy();
    }

    // ---- 렌더러(화면 프로세스)가 죽었을 때: 앱 전체가 꺼지지 않게 새 WebView로 다시 연다 ------------
    /**
     * 메모리 부족(엔진이 렌더러 안 워커에서 돌아 수백 MB를 씀)이나 WebView 업데이트로 렌더러가 죽으면
     * onRenderProcessGone이 온다. 처리하지 않으면 시스템이 앱 프로세스까지 끝낸다.
     * 죽은 WebView는 떼어 내고 없앤 뒤 새 WebView로 첫 화면을 다시 열고 토스트로 알린다.
     * 앱이 뒤에 있으면 앞으로 돌아올 때 연다. 짧은 시간에 거듭 죽으면(다시 열어도 바로 죽는 경우)
     * 되풀이하지 않고 알린 뒤 앱을 닫는다.
     */
    private void onRendererGone(WebView dead) {
        if (dead != web) {   // 이미 바꾼 옛 WebView
            destroyWebView(dead);
            return;
        }
        web = null;
        destroyWebView(dead);
        pageGen++;   // 죽은 페이지가 연 연락처·파일·저장 창의 결과는 새 페이지로 보내지 않는다(토스트로 알림)
        speech.clear();   // 읽던 소리는 멈춘다(알릴 화면이 없다)
        if (tts != null) tts.stop();
        if (fileCallback != null) {   // 죽은 페이지의 파일 고르기는 취소로 끝낸다
            try {
                fileCallback.onReceiveValue(null);
            } catch (RuntimeException ignored) {
                // 죽은 페이지 쪽 콜백
            }
            fileCallback = null;
        }
        if (!resumed) {
            // 뒤에 있을 때(메모리 회수로 죽는 흔한 경우)는 엔진을 다시 띄우지 않고, 앞으로 돌아올 때 연다
            reopenOnResume = true;
            return;
        }
        reopenPage();
    }

    /** 새 WebView로 첫 화면을 연다. 짧은 시간에 거듭 실패하면 되풀이하지 않고 알린 뒤 앱을 닫는다. */
    private void reopenPage() {
        reopenOnResume = false;
        long now = SystemClock.elapsedRealtime();
        if (rendererWindowStart == 0 || now - rendererWindowStart > RENDERER_WINDOW_MS) {
            rendererWindowStart = now;
            rendererRestarts = 0;
        }
        rendererRestarts++;
        if (rendererRestarts > MAX_RENDERER_RESTARTS || isFinishing() || isDestroyed()) {
            toast("화면을 열지 못했어요.\n앱을 다시 열어 주세요.");
            finish();
            return;
        }
        web = createWebView();
        root.addView(web, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        web.loadUrl(START_URL);
        toast("화면을 다시 불러왔어요.");
    }

    /**
     * 화면(페이지)이 받을 수 없는 결과를 알린다. 안드로이드 12+는 토스트 글을 두 줄까지만 보이므로
     * 한 문장 한 줄로 짧게 쓰고 중요한 문장을 앞에 둔다(큰 글씨에서 뒤 문장이 잘려도 뜻이 남게).
     */
    private void toast(String text) {
        // 액티비티가 닫혀도 보이도록 앱 컨텍스트로 띄운다
        runOnUiThread(() -> Toast.makeText(getApplicationContext(), text, Toast.LENGTH_LONG).show());
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
        // configChanges에 uiMode가 있어 액티비티를 다시 만들지 않으므로, 어두운 모드가 바뀌면 막대 색을 직접 바꾼다
        applySystemBars();
    }

    // ---- 상태 표시줄·내비게이션 막대 색(밝게·어둡게) ------------------------------------------
    /** 지금 어둡게 보여야 하는가: 화면 설정(밝게·어둡게)이 있으면 그것, 자동이면 기기 설정. */
    private boolean darkNow() {
        if ("dark".equals(themeMode)) return true;
        if ("light".equals(themeMode)) return false;
        return (getResources().getConfiguration().uiMode & Configuration.UI_MODE_NIGHT_MASK)
                == Configuration.UI_MODE_NIGHT_YES;
    }

    /** res/values(-night)/colors.xml의 bg. 못 읽으면 같은 값을 쓴다. */
    private int barColor(boolean dark) {
        int id = getResources().getIdentifier("bg", "color", getPackageName());
        if (id != 0) {
            try {
                Configuration c = new Configuration(getResources().getConfiguration());
                c.uiMode = (c.uiMode & ~Configuration.UI_MODE_NIGHT_MASK)
                        | (dark ? Configuration.UI_MODE_NIGHT_YES : Configuration.UI_MODE_NIGHT_NO);
                return createConfigurationContext(c).getColor(id);
            } catch (RuntimeException ignored) {
                // 아래 기본값
            }
        }
        return dark ? 0xFF17171C : 0xFFFFFFFF;
    }

    /**
     * 막대 뒤 배경과 막대 아이콘 색을 지금 모드에 맞춘다. targetSdk 35는 화면이 막대 아래까지 그려져서
     * 막대 뒤에 창 배경(windowBackground)이 보인다. 테마 값은 액티비티를 만들 때 한 번만 정해지므로 여기서 다시 칠한다.
     */
    @SuppressWarnings("deprecation")
    private void applySystemBars() {
        Window w = getWindow();
        if (w == null) return;
        boolean dark = darkNow();
        int bg = barColor(dark);
        w.setBackgroundDrawable(new ColorDrawable(bg));
        if (Build.VERSION.SDK_INT < 35) {   // 35부터는 막대가 투명하고 이 값은 쓰이지 않는다
            w.setStatusBarColor(bg);
            w.setNavigationBarColor(bg);
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            WindowInsetsController c = w.getInsetsController();
            if (c != null) {
                int light = WindowInsetsController.APPEARANCE_LIGHT_STATUS_BARS
                        | WindowInsetsController.APPEARANCE_LIGHT_NAVIGATION_BARS;
                c.setSystemBarsAppearance(dark ? 0 : light, light);
            }
        } else {
            View d = w.getDecorView();
            int light = View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR | View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR;
            int f = d.getSystemUiVisibility();
            d.setSystemUiVisibility(dark ? (f & ~light) : (f | light));
        }
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

        @Override
        public boolean onRenderProcessGone(WebView view, RenderProcessGoneDetail detail) {
            if (debuggable) {
                Log.w(TAG, "렌더러 종료(" + (detail != null && detail.didCrash() ? "오류" : "회수·업데이트")
                        + "), 화면을 다시 엽니다");
            }
            onRendererGone(view);
            return true;   // 처리했다: 앱 프로세스는 계속 산다
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

    // ---- 파일 고르기(CSV·TXT·XLSX 올리기) --------------------------------------------------
    private final class Chrome extends WebChromeClient {
        @Override
        public boolean onShowFileChooser(WebView view, ValueCallback<Uri[]> callback,
                                         FileChooserParams params) {
            if (fileCallback != null) fileCallback.onReceiveValue(null);
            fileCallback = callback;
            Intent intent = new Intent(Intent.ACTION_OPEN_DOCUMENT);
            intent.addCategory(Intent.CATEGORY_OPENABLE);
            intent.setType("*/*");
            // 은행·카드사 CSV는 기기마다 MIME가 다르게 붙는다(text/csv, text/comma-separated-values, octet-stream 등).
            // 엑셀 .xlsx(첫 시트를 읽음, safepause/data/xlsx.py)도 고를 수 있어야 한다. 옛 .xls는 화면이 안내만 한다.
            intent.putExtra(Intent.EXTRA_MIME_TYPES, new String[]{
                    "text/csv", "text/comma-separated-values", "application/csv", "text/plain",
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
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
        boolean picked = resultCode == RESULT_OK && data != null && data.getData() != null;
        if (requestCode == REQ_OPEN_FILE) {
            if (fileCallback == null) {
                // 고르는 사이 화면을 다시 불러와(렌더러·앱 다시 시작) 받을 페이지가 없다
                if (picked) toast("고른 파일을 열지 못했어요.\n다시 골라 주세요.");
                return;
            }
            fileCallback.onReceiveValue(picked ? new Uri[]{data.getData()} : null);
            fileCallback = null;
        } else if (requestCode == REQ_SAVE_FILE) {
            finishSave(resultCode, picked ? data.getData() : null);
        } else if (requestCode == REQ_PICK_PHONE || requestCode == REQ_PICK_EMAIL) {
            boolean mine = pickPending.getAndSet(false) && pickGen == pageGen;
            if (!mine) {
                // 선택 창을 연 페이지가 아니다(앱·화면을 다시 불러옴): 연락처는 읽지 않고 다시 고르게 알린다
                if (picked) toast("고른 연락처를 넣지 못했어요.\n다시 골라 주세요.");
                return;
            }
            String kind = requestCode == REQ_PICK_PHONE ? "phone" : "email";
            notifyContact(contactResult(kind, resultCode, data));
        }
    }

    // ---- 파일 저장(시스템 저장 창) -----------------------------------------------------------
    private File saveDir() {
        return new File(getCacheDir(), SAVE_DIR);
    }

    /** 저장할 내용을 cacheDir에 잠시 쓴다(저장 창이 열린 사이 앱이 다시 만들어져도 남게). */
    private File writeSaveCache(byte[] bytes) throws IOException {
        File dir = saveDir();
        if (!dir.isDirectory() && !dir.mkdirs()) throw new IOException("cache dir");
        File f = new File(dir, "save-" + Long.toHexString(System.nanoTime()) + Integer.toHexString(bytes.length) + ".bin");
        try (OutputStream out = new FileOutputStream(f)) {
            out.write(bytes);
        } catch (IOException e) {
            deleteQuietly(f);
            throw e;
        }
        return f;
    }

    /** 열린 저장 창이 쓰는 파일 말고 남은 임시 파일(앱이 꺼지며 남은 것)을 지운다. */
    private void cleanSaveCache() {
        File[] files = saveDir().listFiles();
        if (files == null) return;
        for (File f : files) {
            if (!f.equals(pendingSaveFile)) deleteQuietly(f);
        }
    }

    private static void deleteQuietly(File f) {
        // 못 지우면 다음 시작 때 cleanSaveCache가 다시 지운다(파일 이름·내용은 로그에 남기지 않음)
        if (f != null && !f.delete() && f.exists()) Log.w(TAG, "임시 파일을 지우지 못했어요");
    }

    /**
     * 저장 창 결과. 시스템 저장 창은 [저장]을 누르는 순간 빈 문서를 만들므로, 내용을 쓰지 못하면
     * 그 빈(또는 쓰다 만) 문서를 지우고 실패로 알린다. 창을 연 페이지가 아니면(앱·화면을 다시 불러옴) 토스트로 알린다.
     */
    private void finishSave(int resultCode, Uri uri) {
        String token = pendingSaveToken;
        File tmp = pendingSaveFile;
        boolean mine = saveGen == pageGen;
        pendingSaveToken = null;
        pendingSaveFile = null;
        savePending.set(false);
        String status;
        if (resultCode != RESULT_OK || uri == null) {
            status = "cancelled";
        } else {
            boolean ok = tmp != null && tmp.isFile() && copyToDocument(tmp, uri);
            if (!ok) deleteDocumentQuietly(uri);
            status = ok ? "saved" : "error";
        }
        deleteQuietly(tmp);
        if (mine && token != null) {
            notifySave(token, status);
        } else if ("saved".equals(status)) {
            toast("파일을 저장했어요.");
        } else if ("error".equals(status)) {
            toast("파일을 저장하지 못했어요.\n다시 저장해 주세요.");
        }
    }

    private boolean copyToDocument(File src, Uri uri) {
        try (InputStream in = new FileInputStream(src);
             OutputStream out = getContentResolver().openOutputStream(uri, "w")) {
            if (out == null) return false;
            byte[] buf = new byte[64 * 1024];
            for (int n; (n = in.read(buf)) > 0; ) out.write(buf, 0, n);
            out.flush();
            return true;
        } catch (IOException | RuntimeException e) {   // SecurityException·IllegalArgumentException 등
            return false;
        }
    }

    private void deleteDocumentQuietly(Uri uri) {
        try {
            DocumentsContract.deleteDocument(getContentResolver(), uri);
        } catch (Exception e) {   // FileNotFoundException·SecurityException·지우기를 못 하는 저장소
            if (debuggable) Log.w(TAG, "빈 문서를 지우지 못했어요: " + e.getClass().getSimpleName());
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

    /** 문자·메일·다이얼 주소를 나눈 것: 종류, 받는 사람(아직 % 표기 그대로), 쿼리(푼 값). */
    static final class ExternalParts {
        final String scheme;
        final String rawTarget;
        final Map<String, String> params;

        ExternalParts(String scheme, String rawTarget, Map<String, String> params) {
            this.scheme = scheme;
            this.rawTarget = rawTarget;
            this.params = params;
        }
    }

    /**
     * 주소를 나누고 길이를 확인한다. 허용하지 않는 종류이거나 너무 길면 null.
     * 글(body)·제목(subject)은 주소가 아니라 Intent extra로 넘어가므로, 인코딩된 주소 길이가 아니라
     * 푼 글자 수로 잰다(한글 1,000자 글은 주소로 9,000자가 넘지만 문자 앱에는 1,000자로 간다).
     */
    static ExternalParts splitExternal(String uri) {
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
        if (rest.length() > MAX_EXTERNAL_TARGET * 3) return null;   // %XX 꼴이어도 넘는 받는 사람 묶음
        Map<String, String> params = parseQuery(query);
        String body = params.get("body");
        String subject = params.get("subject");
        if (body != null && body.length() > MAX_EXTERNAL_TEXT) return null;
        if (subject != null && subject.length() > MAX_EXTERNAL_SUBJECT) return null;
        return new ExternalParts(scheme, rest, params);
    }

    static Intent externalIntent(String uri) {
        ExternalParts parts = splitExternal(uri);
        if (parts == null) return null;
        String scheme = parts.scheme;
        String target = Uri.decode(parts.rawTarget).trim();
        if (target.length() > MAX_EXTERNAL_TARGET) return null;
        Map<String, String> params = parts.params;
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
                // 받는 사람만 주소에 남기고 제목·글은 extra로 넘긴다
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

    /**
     * 연락처 선택 창을 연다. 이미 열려 있으면(빠른 두 번 누르기 등) 새로 열지 않고 false를 돌려준다.
     * 이때 앞서 연 창의 결과는 그대로 __safepauseContactPicked로 한 번 온다(화면은 앞 요청을 계속 기다리면 된다).
     */
    boolean startPickContact(String kind) {
        final String k = kind == null ? "" : kind.trim().toLowerCase(Locale.ROOT);
        final Intent intent = pickIntent(k);
        if (intent == null || isFinishing() || !canResolve(intent)) return false;
        if (!pickPending.compareAndSet(false, true)) return false;
        runOnUiThread(() -> {
            pickGen = pageGen;
            try {
                startActivityForResult(intent, "phone".equals(k) ? REQ_PICK_PHONE : REQ_PICK_EMAIL);
            } catch (ActivityNotFoundException | SecurityException e) {
                pickPending.set(false);
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
        if (speech.end(utteranceId)) notifySpeechDone(reason);
    }

    private void notifySpeechDone(String reason) {
        callJs("window.__safepauseSpeechDone && window.__safepauseSpeechDone(" + jsString(reason) + ")");
    }

    /** 읽기를 멈추고, 읽던 것이 있었으면 끝남을 바로 알린다(엔진에 따라 onStop이 오지 않을 수 있음). */
    private void stopSpeech() {
        boolean had = speech.clear();
        if (tts != null) tts.stop();
        if (had) notifySpeechDone("stopped");
    }

    /**
     * 지금 읽는 발화의 id. 끝남 알림(onDone·onError·onStop)의 id는 TTS 서비스(다른 프로세스)에서
     * Binder로 넘어온 새 String이라 speak()가 넣은 것과 참조가 다르다. 그래서 참조(==)가 아니라 값(equals)으로
     * 비교한다(AtomicReference.compareAndSet은 참조로 비교하므로 그대로 쓰면 끝남 알림이 늘 버려진다).
     * 안드로이드 API를 쓰지 않아 JVM에서 시험할 수 있다(android/check/ShellCheck.java).
     */
    static final class SpeechTurn {
        private final AtomicInteger seq = new AtomicInteger();
        private final AtomicReference<String> current = new AtomicReference<>();

        /** 새 발화 id를 만들어 지금 것으로 둔다. 앞 발화의 늦은 끝남 알림은 이제 맞지 않아 걸러진다. */
        String begin() {
            String id = "safepause-" + seq.incrementAndGet();
            current.set(id);
            return id;
        }

        /** 지금 발화의 끝남이면 비우고 true(한 번만). 옛 발화·이미 끝난 발화·null이면 false. */
        boolean end(String id) {
            if (id == null) return false;
            while (true) {
                String cur = current.get();
                if (cur == null || !cur.equals(id)) return false;
                if (current.compareAndSet(cur, null)) return true;   // cur는 current에서 꺼낸 그 참조
            }
        }

        /** 멈추기: 읽던 것이 있었으면 true. 그 뒤에 오는 onStop은 end()에서 걸러진다. */
        boolean clear() {
            return current.getAndSet(null) != null;
        }

        boolean active() {
            return current.get() != null;
        }
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
            String id = speech.begin();   // 먼저 바꿔 둬야 QUEUE_FLUSH로 밀린 옛 읽기의 onStop을 거른다
            boolean ok = engine.speak(t, TextToSpeech.QUEUE_FLUSH, p, id) == TextToSpeech.SUCCESS;
            if (!ok) speech.end(id);
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
         * 선택 창이 이미 열려 있으면 false(새 창을 열지 않음). 이때 앞 창의 결과는 그대로 한 번 온다.
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

        /**
         * 시스템 저장 창을 열어 파일을 저장한다. 결과는 window.__safepauseSaveDone(token, status)로 알린다
         * (status: saved | cancelled | error). 저장 창이 이미 열려 있거나 내용을 읽지 못하면 false.
         * 내용은 저장 창이 열린 동안 cacheDir에 잠시 두므로, 그사이 앱이 다시 만들어져도 저장되거나(토스트로 알림)
         * 빈 파일 없이 실패로 끝난다.
         */
        @JavascriptInterface
        public boolean saveFile(String token, String filename, String mime, String base64) {
            if (token == null || filename == null || base64 == null || base64.length() > 30_000_000) return false;
            final byte[] bytes;
            try {
                bytes = Base64.decode(base64, Base64.DEFAULT);
            } catch (IllegalArgumentException e) {
                return false;
            }
            if (!savePending.compareAndSet(false, true)) return false;   // 저장 창은 한 번에 하나
            final File tmp;
            try {
                tmp = writeSaveCache(bytes);
            } catch (IOException | RuntimeException e) {
                savePending.set(false);
                return false;
            }
            runOnUiThread(() -> {
                if (isFinishing() || isDestroyed()) {
                    deleteQuietly(tmp);
                    savePending.set(false);
                    notifySave(token, "error");
                    return;
                }
                pendingSaveFile = tmp;
                pendingSaveToken = token;
                saveGen = pageGen;
                Intent intent = new Intent(Intent.ACTION_CREATE_DOCUMENT);
                intent.addCategory(Intent.CATEGORY_OPENABLE);
                intent.setType(mime == null || mime.isEmpty() ? "application/octet-stream" : mime);
                intent.putExtra(Intent.EXTRA_TITLE, filename.replaceAll("[\\\\/:*?\"<>|]", "_"));
                try {
                    startActivityForResult(intent, REQ_SAVE_FILE);
                } catch (ActivityNotFoundException | SecurityException e) {
                    pendingSaveFile = null;
                    pendingSaveToken = null;
                    deleteQuietly(tmp);
                    savePending.set(false);
                    notifySave(token, "error");
                }
            });
            return true;
        }

        /**
         * 화면 설정의 화면 모드(auto | light | dark)를 알려 주면 상태 표시줄·내비게이션 막대 색을 맞춘다.
         * 모르는 값은 auto(기기 설정을 따름).
         */
        @JavascriptInterface
        public void setThemeMode(String mode) {
            final String m = "light".equals(mode) || "dark".equals(mode) ? mode : "auto";
            runOnUiThread(() -> {
                themeMode = m;
                applySystemBars();
            });
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
        // 저장 창이 열린 채 앱이 회수돼도 다시 만들어진 뒤 그 내용을 저장할 수 있게 임시 파일 이름을 남긴다
        if (pendingSaveFile != null) {
            outState.putString(STATE_SAVE_FILE, pendingSaveFile.getName());
            outState.putString(STATE_SAVE_TOKEN, pendingSaveToken);
        }
        outState.putString(STATE_THEME, themeMode);
    }

    /** onSaveInstanceState가 남긴 것을 되살린다. 저장은 새 페이지가 모르는 요청이므로 결과를 토스트로 알린다. */
    private void restoreNativeState(Bundle state) {
        String mode = state.getString(STATE_THEME);
        if ("light".equals(mode) || "dark".equals(mode)) themeMode = mode;
        String name = state.getString(STATE_SAVE_FILE);
        if (name != null && SAVE_NAME.matcher(name).matches()) {
            pendingSaveFile = new File(saveDir(), name);
            pendingSaveToken = state.getString(STATE_SAVE_TOKEN);
            saveGen = -1;   // 이 페이지가 연 저장 창이 아니다
            savePending.set(true);
        }
    }

    @Override
    protected void onPause() {
        super.onPause();
        resumed = false;
        stopSpeech();   // 화면을 떠나면 읽기를 멈추고 소리 버튼도 원래대로
        if (web != null) web.onPause();
    }

    @Override
    protected void onResume() {
        super.onResume();
        resumed = true;
        // 되살린 저장 요청인데 결과 없이 화면이 돌아왔다(결과는 onResume 전에 온다): 임시 파일을 지우고 끝낸다
        if (saveGen == -1 && pendingSaveFile != null) {
            deleteQuietly(pendingSaveFile);
            pendingSaveFile = null;
            pendingSaveToken = null;
            savePending.set(false);
        }
        if (web == null && reopenOnResume) reopenPage();
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
            destroyWebView(web);
            web = null;
        }
        // 앱을 닫을 때만 저장 임시 파일을 지운다(다시 만들어질 때는 onSaveInstanceState가 이름을 넘겨 이어 쓴다)
        if (isFinishing() && pendingSaveFile != null) {
            deleteQuietly(pendingSaveFile);
            pendingSaveFile = null;
        }
        super.onDestroy();
    }
}
