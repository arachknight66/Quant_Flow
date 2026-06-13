// apps/mobile/app.config.ts
import type { ExpoConfig, ConfigContext } from "expo/config";

export default ({ config }: ConfigContext): ExpoConfig => ({
  ...config,
  name: "QuantPlatform",
  slug: "quant-platform",
  version: "1.0.0",
  orientation: "portrait",
  icon: "./assets/icon.png",
  userInterfaceStyle: "dark",
  splash: {
    image: "./assets/splash.png",
    resizeMode: "contain",
    backgroundColor: "#0a0e1a",
  },
  assetBundlePatterns: ["**/*"],
  ios: {
    supportsTablet: true,
    bundleIdentifier: "com.yourcompany.quantplatform",
  },
  android: {
    adaptiveIcon: {
      foregroundImage: "./assets/adaptive-icon.png",
      backgroundColor: "#0a0e1a",
    },
    package: "com.yourcompany.quantplatform",
    // Required for background price refresh
    permissions: [
      "RECEIVE_BOOT_COMPLETED",
      "VIBRATE",
      "INTERNET",
      "ACCESS_NETWORK_STATE",
    ],
  },
  plugins: [
    "expo-router",
    [
      "expo-notifications",
      {
        // Push notification configuration
        icon: "./assets/notification-icon.png",
        color: "#00d4ff",
        sounds: ["./assets/notification.wav"],
      },
    ],
    [
      "expo-build-properties",
      {
        android: {
          compileSdkVersion: 34,
          targetSdkVersion: 34,
          buildToolsVersion: "34.0.0",
        },
      },
    ],
  ],
  extra: {
    apiUrl: process.env.EXPO_PUBLIC_API_URL ?? "https://api.yourplatform.com/api/v1",
    wsUrl: process.env.EXPO_PUBLIC_WS_URL ?? "wss://api.yourplatform.com/ws",
    eas: {
      projectId: process.env.EAS_PROJECT_ID,
    },
  },
  updates: {
    // OTA updates — push bug fixes without going through Play Store review
    url: `https://u.expo.dev/${process.env.EAS_PROJECT_ID}`,
    enabled: true,
    checkAutomatically: "ON_LOAD",
    fallbackToCacheTimeout: 0,
  },
  runtimeVersion: {
    policy: "sdkVersion",
  },
});