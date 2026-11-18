plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}
android {
    namespace = "com.shimokin.jlclogin"
    compileSdk = 35
    defaultConfig {
        applicationId = "com.shimokin.jlclogin"
        minSdk = 23
        targetSdk = 35
        versionCode = 1
        versionName = "1.0.0"
    }
}
dependencies {
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
}
