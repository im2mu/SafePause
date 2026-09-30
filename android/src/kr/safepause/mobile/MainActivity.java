package kr.safepause.mobile;

import android.app.Activity;
import android.content.ActivityNotFoundException;
import android.content.Intent;
import android.content.pm.ApplicationInfo;
import android.content.res.Configuration;
import android.graphics.Insets;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.speech.tts.TextToSpeech;
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

import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.util.Collections;
import java.util.HashMap;
import java.util.Locale;
import java.util.Map;

/**
 * SafePause 안드로이드 셸.
 *
 * <p>화면(HTML·JS)과 AI 엔진(Pyodide 파이썬·scikit-learn)은 모두 APK의 assets/www에 들어 있다.
 * WebView가 https://app.safepause.local/ 로 요청하면 {@link #shouldInterceptRequest}가 assets에서
 * 꺼내 준다. 그 밖의 주소는 모두 403으로 막는다. 앱은 INTERNET 권한이 없어 기기 밖으로 나가는
 * 통로가 운영체제 수준에서 없다.</p>
 *
 * <p>JS 다리(window.SafePauseNative): 기기 안 음성(TTS) 읽기, 파일 저장(시스템 저장 창).</p>
 */
public class MainActivity extends Activity {
    static final String HOST = "app.safepause.local";
    static final String ORIGIN = "https://" + HOST;
    static final String START_URL = ORIGIN + "/index.html";
    private static final String TAG = "SafePause";
    private static final int REQ_OPEN_FILE = 41;
    private static final int REQ_SAVE_FILE = 42;
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
            return !(HOST.equals(url.getHost()) && "https".equals(url.getScheme()));   // 앱 밖으로 이동 금지
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
        }
    }

    private void notifySave(String token, String status) {
        if (token == null || web == null) return;
        String js = "window.__safepauseSaveDone && window.__safepauseSaveDone("
                + jsString(token) + "," + jsString(status) + ")";
        web.post(() -> web.evaluateJavascript(js, null));
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
        ttsState = "ready";
    }

    private final class NativeBridge {
        @JavascriptInterface
        public String ttsStatus() {
            return ttsState;
        }

        @JavascriptInterface
        public boolean speak(String text) {
            if (!"ready".equals(ttsState) || tts == null || text == null) return false;
            Bundle p = new Bundle();
            p.putString(TextToSpeech.Engine.KEY_FEATURE_EMBEDDED_SYNTHESIS, "true");
            String t = text.length() > 3000 ? text.substring(0, 3000) : text;
            return tts.speak(t, TextToSpeech.QUEUE_FLUSH, p, "safepause") == TextToSpeech.SUCCESS;
        }

        @JavascriptInterface
        public void stopSpeaking() {
            if (tts != null) tts.stop();
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
        if (tts != null) tts.stop();
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
