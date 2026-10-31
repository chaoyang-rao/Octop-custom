import Foundation

struct NativeStrings {
    static var mode: String {
        get { UserDefaults.standard.string(forKey: "octop.native.language-mode") ?? "account" }
        set { UserDefaults.standard.set(newValue, forKey: "octop.native.language-mode") }
    }
    static var systemLanguage: String { (Locale.preferredLanguages.first ?? "en").hasPrefix("zh") ? "zh" : "en" }
    static var language: String {
        if ["zh", "en"].contains(mode) { return mode }
        return UserDefaults.standard.string(forKey: "octop.native.account-locale") ?? systemLanguage
    }
    static func accountLanguage(_ language: String) {
        UserDefaults.standard.set(language.hasPrefix("zh") ? "zh" : "en", forKey: "octop.native.account-locale")
    }
    static func text(_ key: String, locale: String? = nil, values: [Any] = []) -> String {
        let language = locale?.hasPrefix("zh") == true ? "zh" : locale == nil ? self.language : "en"
        let bundle = Bundle.main.path(forResource: language, ofType: "lproj").flatMap(Bundle.init(path:)) ?? Bundle.main
        let format = bundle.localizedString(forKey: key, value: key, table: nil)
        return String(format: format, locale: Locale(identifier: language), arguments: values.map { String(describing: $0) as CVarArg })
    }
}
func L(_ key: String, _ values: Any..., locale: String? = nil) -> String {
    NativeStrings.text(key, locale: locale, values: values)
}
