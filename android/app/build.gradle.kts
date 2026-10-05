plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "kr.submoa.app"
    compileSdk = 35

    defaultConfig {
        applicationId = "kr.submoa.app"
        minSdk = 26
        targetSdk = 35
        versionCode = 1
        versionName = "0.1.0"

        // 기본값은 APK 안에 넣은 웹 앱(저장소 루트에서 `npm run export` → out/)의 홈.
        // 홈은 설정을 마치지 않은 사용자를 온보딩으로 보낸다.
        // 개발 PC의 `npm run dev`에 붙일 때(에뮬레이터):
        //   ./gradlew installDebug -Psubmoa.webUrl=http://10.0.2.2:3000/
        val webUrl = (project.findProperty("submoa.webUrl") as String?)
            ?: "https://appassets.androidplatform.net/"
        buildConfigField("String", "WEB_URL", "\"$webUrl\"")
    }

    buildFeatures {
        buildConfig = true
    }

    buildTypes {
        debug {
            // 개발 서버가 http라서 디버그 빌드에서만 평문 통신을 허용한다
            manifestPlaceholders["cleartext"] = "true"
        }
        release {
            isMinifyEnabled = false
            manifestPlaceholders["cleartext"] = "false"
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }

    sourceSets["main"].assets.srcDir(layout.buildDirectory.dir("generated/webassets"))

    androidResources {
        // 기본 규칙(aapt)은 `_`로 시작하는 폴더를 APK에서 뺀다. Next의 CSS·JS가 전부 `_next/`에 있어서,
        // 기본값이면 HTML만 들어가고 화면이 깨지고 버튼이 안 눌린다. 기본값에서 `<dir>_*`만 지운 규칙이다.
        // 확인: node ../scripts/verify-apk-assets.mjs app/build/outputs/apk/debug/app-debug.apk
        ignoreAssetsPattern = "!.svn:!.git:!.ds_store:!*.scc:.*:!CVS:!thumbs.db:!picasa.ini:!*~"
    }
}

// 웹 앱 정적 파일을 assets/web/으로 복사한다. out/이 없으면 먼저 `npm run export`.
val syncWebAssets by tasks.registering(Sync::class) {
    from(rootProject.file("../out"))
    into(layout.buildDirectory.dir("generated/webassets/web"))
    doFirst {
        if (!rootProject.file("../out/onboarding.html").exists()) {
            logger.warn("out/이 없습니다. 저장소 루트에서 `npm run export`를 먼저 실행하세요. 웹 화면 없이 빌드됩니다.")
        }
    }
}
tasks.named("preBuild") { dependsOn(syncWebAssets) }

dependencies {
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.webkit:webkit:1.12.1")
    // 스토어 구독 스크린샷 글자 인식 (온디바이스, 한국어).
    // Play 서비스가 모델을 따로 내려받는 경량 버전 — APK에 모델을 넣지 않아 용량이 작다.
    implementation("com.google.android.gms:play-services-mlkit-text-recognition-korean:16.0.1")
    testImplementation("junit:junit:4.13.2")
}
