import com.android.build.api.variant.BuildConfigField
import java.net.URI

plugins { id("com.android.application") }

val dotenvOrigin = providers.fileContents(rootProject.layout.projectDirectory.file("../.env"))
    .asText.orElse("").map { contents ->
        contents.lineSequence().firstOrNull { it.substringBefore('=').trim() == "PUBLIC_ORIGIN" }
            ?.substringAfter('=')?.trim()?.removeSurrounding("\"")?.removeSurrounding("'").orEmpty()
    }
val publicApiUrl = providers.environmentVariable("PUBLIC_ORIGIN").orElse(dotenvOrigin).map { value ->
    val origin = value.trim().trimEnd('/')
    val uri = runCatching { URI(origin) }.getOrNull()
    require(uri != null && uri.scheme == "https" && !uri.host.isNullOrBlank() &&
        uri.rawUserInfo == null && uri.rawPath.isNullOrEmpty() && uri.rawQuery == null && uri.rawFragment == null) {
        "Set PUBLIC_ORIGIN to an HTTPS origin (e.g. https://api.talkdock.app) in the repository .env or environment."
    }
    "\"$origin/api/\""
}

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
        debug {
            manifestPlaceholders["cleartextAllowed"] = "true"
            // JaCoCo reports: createDebugUnitTestCoverageReport and createDebugAndroidTestCoverageReport.
            enableUnitTestCoverage = true
            enableAndroidTestCoverage = true
        }
        release {
            isMinifyEnabled = false
            // Keep APK sharing installable with the existing development certificate.
            signingConfig = signingConfigs.getByName("debug")
        }
    }
    buildFeatures { buildConfig = true }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}

androidComponents {
    onVariants(selector().withBuildType("release")) { variant ->
        variant.buildConfigFields!!.put("API_URL", publicApiUrl.map { BuildConfigField("String", it, null) })
    }
}

tasks.register<Copy>("assembleApks") {
    group = "build"
    description = "Build local development and public-server APKs."
    dependsOn("assembleDebug", "assembleRelease")
    from(layout.buildDirectory.file("outputs/apk/debug/app-debug.apk")) {
        rename { "talkdock_local_dev.apk" }
    }
    from(layout.buildDirectory.file("outputs/apk/release/app-release.apk")) {
        rename { "talkdock.apk" }
    }
    into(layout.buildDirectory.dir("outputs/apk/distribution"))
}

dependencies {
    implementation("com.caverock:androidsvg-aar:1.4")
    implementation("androidx.core:core-ktx:1.10.1")
    implementation("androidx.activity:activity-ktx:1.10.1")
    implementation("androidx.swiperefreshlayout:swiperefreshlayout:1.2.0")
    testImplementation("junit:junit:4.13.2")
    // android.jar's org.json is a stub on the JVM; unit tests need the real implementation.
    testImplementation("org.json:json:20240303")
    androidTestImplementation("androidx.test:runner:1.6.2")
    androidTestImplementation("androidx.test.ext:junit:1.2.1")
}
