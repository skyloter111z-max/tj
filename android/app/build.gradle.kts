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

        // 웹 앱 주소. 기본값은 에뮬레이터에서 본 개발 PC의 `npm run dev`.
        // 배포 주소로 빌드할 때: ./gradlew assembleRelease -Psubmoa.webUrl=https://...
        val webUrl = (project.findProperty("submoa.webUrl") as String?)
            ?: "http://10.0.2.2:3000/onboarding"
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
}

dependencies {
    implementation("androidx.core:core-ktx:1.13.1")
    testImplementation("junit:junit:4.13.2")
}
