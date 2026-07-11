import * as Notifications from "expo-notifications";
import * as Device from "expo-device";
import { Platform } from "react-native";

const API_URL = process.env.EXPO_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";

Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowAlert: true,
    shouldPlaySound: true,
    shouldSetBadge:  true,
  }),
});

export interface PushToken {
  token:    string;
  platform: "ios" | "android";
}

export async function registerForPushNotifications(): Promise<PushToken | null> {
  if (!Device.isDevice) {
    console.warn("Push notifications require a physical device");
    return null;
  }

  const { status: existing } = await Notifications.getPermissionsAsync();
  let final = existing;
  if (existing !== "granted") {
    const { status } = await Notifications.requestPermissionsAsync();
    final = status;
  }
  if (final !== "granted") {
    console.warn("Push notification permission denied");
    return null;
  }

  if (Platform.OS === "android") {
    await Notifications.setNotificationChannelAsync("signals", {
      name: "Trading signals",
      importance: Notifications.AndroidImportance.HIGH,
      vibrationPattern: [0, 250, 250, 250],
      lightColor: "#00d4ff",
      sound: "notification.wav",
    });
    await Notifications.setNotificationChannelAsync("risk_alerts", {
      name: "Risk alerts",
      importance: Notifications.AndroidImportance.MAX,
      vibrationPattern: [0, 500, 200, 500],
      lightColor: "#ff4466",
      bypassDnd: true,
    });
  }

  const tokenData = await Notifications.getExpoPushTokenAsync({
    projectId: process.env.EXPO_PUBLIC_EAS_PROJECT_ID,
  });

  return { token: tokenData.data, platform: Platform.OS as "ios" | "android" };
}

export async function registerTokenWithBackend(tokenData: PushToken): Promise<void> {
  await fetch(`${API_URL}/notifications/register-token`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      expo_push_token: tokenData.token,
      platform:        tokenData.platform,
    }),
  });
}

export function useNotificationNavigation(navigation: any) {
  Notifications.useLastNotificationResponse((response) => {
    if (!response) return;
    const data = response.notification.request.content.data as any;
    switch (data?.type) {
      case "SIGNAL":      navigation.navigate("Analysis", { symbol: data.symbol }); break;
      case "PRICE_ALERT": navigation.navigate("AssetDetail", { symbol: data.symbol }); break;
      case "RISK_ALERT":  navigation.navigate("Portfolio"); break;
    }
  });
}
