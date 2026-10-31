package com.octop.mobile;

import android.content.Context;
import android.content.res.Configuration;
import java.util.Locale;

final class NativeStrings {
    private static Context application;
    static void initialize(Context context) { application = context.getApplicationContext(); }
    static String mode() { return application.getSharedPreferences("octop-mobile", Context.MODE_PRIVATE).getString("native_language_mode", "account"); }
    static void mode(String value) { application.getSharedPreferences("octop-mobile", Context.MODE_PRIVATE).edit().putString("native_language_mode", value).apply(); }
    static void accountLanguage(String value) { application.getSharedPreferences("octop-mobile", Context.MODE_PRIVATE).edit().putString("native_account_locale", value.startsWith("zh") ? "zh" : "en").apply(); }
    static Locale locale() {
        String mode = mode();
        if (mode.equals("zh") || mode.equals("en")) return Locale.forLanguageTag(mode);
        String fallback = Locale.getDefault().getLanguage().startsWith("zh") ? "zh" : "en";
        return Locale.forLanguageTag(application.getSharedPreferences("octop-mobile", Context.MODE_PRIVATE).getString("native_account_locale", fallback));
    }
    static String text(String key, Object... values) {
        Configuration configuration = new Configuration(application.getResources().getConfiguration()); configuration.setLocale(locale());
        Context context = application.createConfigurationContext(configuration);
        int id = context.getResources().getIdentifier(key, "string", context.getPackageName());
        String format = id == 0 ? key : context.getString(id);
        return values.length == 0 ? format : String.format(locale(), format, values);
    }
}
