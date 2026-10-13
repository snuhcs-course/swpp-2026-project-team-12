plugins { id("com.android.application") }

android {
    namespace = "kr.talkdock.app"
    compileSdk = 36
    defaultConfig {
        applicationId = "kr.talkdock.app"
        minSdk = 26
        targetSdk = 36
        versionCode = 1
        versionName = "0.1.0"
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
        val apiUrl = providers.gradleProperty("talkDockApiUrl").getOrElse("http://10.0.2.2:8000/api/")
        buildConfigField("String", "API_URL", "\"" + apiUrl + "\"")
        manifestPlaceholders["cleartextAllowed"] = "false"
    }
    buildTypes {
        debug { manifestPlaceholders["cleartextAllowed"] = "true" }
        release { isMinifyEnabled = false }
    }
    buildFeatures { buildConfig = true }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}
dependencies {
    implementation("androidx.core:core-ktx:1.10.1")
    implementation("androidx.activity:activity-ktx:1.10.1")
    testImplementation("junit:junit:4.13.2")
    androidTestImplementation("androidx.test:runner:1.6.2")
    androidTestImplementation("androidx.test.ext:junit:1.2.1")
}
