// apps/mobile/src/notifications/push_notifications.ts
/**
 * Push notification setup for real-time price alerts and signal notifications.
 *
 * Flow:
 * 1. On first launch, request notification permissions
 * 2. Get Expo push token (unique device identifier)
 * 3. Register token with backend (stored against user_id)
 * 4. Backend sends push via Expo Push API when signals fire
 *
 * Categories of notifications:
 * - SIGNAL: New BUY/SELL recommendation (high priority)
 * - PRICE_ALERT: Watchlist price threshold crossed (medium priority)
 * - RISK_ALERT: Position approaching stop-loss (critical)
 * - REGIME_CHANGE: Market regime shift detected (low priority)
 */
import * as Notifications from "expo-notifications";
import * as Device from "expo-device";
import { Platform } from "react-native";
import { api } from "@/lib/api-client";

// Configure how notifications behave when the app is in foreground
Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowAlert: true,
    shouldPlaySound: true,
    shouldSetBadge: true,
  }),
});

export interface PushToken {
  token: string;
  platform: "ios" | "android";
}

export async function registerForPushNotifications(): Promise<PushToken | null> {
  if (!Device.isDevice) {
    console.warn("Push notifications require a physical device");
    return null;
  }

  const { status: existingStatus } = await Notifications.getPermissionsAsync();
  let finalStatus = existingStatus;

  if (existingStatus !== "granted") {
    const { status } = await Notifications.requestPermissionsAsync();
    finalStatus = status;
  }

  if (finalStatus !== "granted") {
    console.warn("Push notification permission denied");
    return null;
  }

  if (Platform.OS === "android") {
    // Android notification channels (required for Android 8+)
    await Notifications.setNotificationChannelAsync("signals", {
      name: "Trading signals",
      importance: Notifications.AndroidImportance.HIGH,
      vibrationPattern: [0, 250, 250, 250],
      lightColor: "#00d4ff",
      sound: "notification.wav",
    });

    await Notifications.setNotificationChannelAsync("price_alerts", {
      name: "Price alerts",
      importance: Notifications.AndroidImportance.DEFAULT,
      sound: "default",
    });

    await Notifications.setNotificationChannelAsync("risk_alerts", {
      name: "Risk alerts",
      importance: Notifications.AndroidImportance.MAX,
      vibrationPattern: [0, 500, 200, 500],
      lightColor: "#ff4466",
      bypassDnd: true, // Override Do Not Disturb for critical risk alerts
    });
  }

  const tokenData = await Notifications.getExpoPushTokenAsync({
    projectId: process.env.EXPO_PUBLIC_EAS_PROJECT_ID,
  });

  return {
    token: tokenData.data,
    platform: Platform.OS as "ios" | "android",
  };
}

export async function registerTokenWithBackend(tokenData: PushToken): Promise<void> {
  await api.notifications.registerToken({
    expo_push_token: tokenData.token,
    platform: tokenData.platform,
  });
}

export function useNotificationNavigation(navigation: any) {
  /**
   * Handle notification taps — navigate to the relevant screen.
   * Different notification types navigate to different screens.
   */
  Notifications.useLastNotificationResponse((response) => {
    if (!response) return;
    const data = response.notification.request.content.data as any;

    switch (data?.type) {
      case "SIGNAL":
        navigation.navigate("Analysis", { symbol: data.symbol });
        break;
      case "PRICE_ALERT":
        navigation.navigate("AssetDetail", { symbol: data.symbol });
        break;
      case "RISK_ALERT":
        navigation.navigate("Portfolio");
        break;
    }
  });
}