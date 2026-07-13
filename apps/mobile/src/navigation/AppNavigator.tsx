import React from "react";
import { createBottomTabNavigator } from "@react-navigation/bottom-tabs";
import { AnalysisScreen } from "../screens/AnalysisScreen";
import { PortfolioScreen } from "../screens/PortfolioScreen";
import { WatchlistScreen } from "../screens/WatchlistScreen";
import { SettingsScreen } from "../screens/SettingsScreen";
import { Text } from "react-native";

const Tab = createBottomTabNavigator();

export function AppNavigator() {
  return (
    <Tab.Navigator
      screenOptions={({ route }) => ({
        headerStyle: {
          backgroundColor: "#0f1628",
          borderBottomWidth: 1,
          borderBottomColor: "#1e2d4f",
        },
        headerTitleStyle: {
          color: "#c8d8f0",
          fontWeight: "700",
          fontSize: 16,
        },
        tabBarStyle: {
          backgroundColor: "#0f1628",
          borderTopWidth: 1,
          borderTopColor: "#1e2d4f",
          height: 60,
          paddingBottom: 8,
          paddingTop: 8,
        },
        tabBarActiveTintColor: "#00d4ff",
        tabBarInactiveTintColor: "#6a82a8",
        tabBarLabelStyle: {
          fontSize: 10,
          fontWeight: "600",
        },
      })}
    >
      <Tab.Screen name="Analysis" component={AnalysisScreen} options={{
        title: "Analysis",
        tabBarIcon: ({ color }) => <Text style={{ color, fontSize: 18 }}>📈</Text>
      }} />
      <Tab.Screen name="Portfolio" component={PortfolioScreen} options={{
        title: "Portfolio",
        tabBarIcon: ({ color }) => <Text style={{ color, fontSize: 18 }}>💼</Text>
      }} />
      <Tab.Screen name="Watchlist" component={WatchlistScreen} options={{
        title: "Watchlist",
        tabBarIcon: ({ color }) => <Text style={{ color, fontSize: 18 }}>⭐</Text>
      }} />
      <Tab.Screen name="Settings" component={SettingsScreen} options={{
        title: "Settings",
        tabBarIcon: ({ color }) => <Text style={{ color, fontSize: 18 }}>⚙️</Text>
      }} />
    </Tab.Navigator>
  );
}
