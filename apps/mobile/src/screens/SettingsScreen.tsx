import React, { useState } from "react";
import { View, Text, ScrollView, StyleSheet, TouchableOpacity, TextInput, Alert } from "react-native";

export function SettingsScreen() {
  const [riskTolerance, setRiskTolerance] = useState<"conservative"|"moderate"|"aggressive">("moderate");
  const [capital, setCapital] = useState("10000");
  const [pushEnabled, setPushEnabled] = useState(true);

  const handleSave = () => {
    Alert.alert("Settings saved", "Your mobile preferences have been saved locally.");
  };

  return (
    <ScrollView style={s.container} contentContainerStyle={s.content}>
      <Text style={s.title}>Settings</Text>

      <View style={s.section}>
        <Text style={s.sectionTitle}>Default Risk Profile</Text>
        <View style={s.row}>
          {(["conservative","moderate","aggressive"] as const).map((r) => (
            <TouchableOpacity key={r}
              style={[s.chip, riskTolerance === r && s.chipActive]}
              onPress={() => setRiskTolerance(r)}>
              <Text style={[s.chipText, riskTolerance === r && s.chipTextActive]}>
                {r[0].toUpperCase() + r.slice(1)}
              </Text>
            </TouchableOpacity>
          ))}
        </View>
      </View>

      <View style={s.section}>
        <Text style={s.sectionTitle}>Available Sizing Capital (USD)</Text>
        <TextInput style={s.input} value={capital} onChangeText={setCapital}
          keyboardType="numeric" placeholder="e.g. 10000" placeholderTextColor="#3a4f78" />
      </View>

      <View style={s.section}>
        <Text style={s.sectionTitle}>Push Notifications</Text>
        <TouchableOpacity style={[s.positionRow, { justifyContent: "space-between" }]}
                          onPress={() => setPushEnabled(!pushEnabled)}>
          <Text style={s.label}>Enable Signal Alerts</Text>
          <Text style={{ color: pushEnabled ? "#00e5a0" : "#ff4466", fontWeight: "700" }}>
            {pushEnabled ? "ON" : "OFF"}
          </Text>
        </TouchableOpacity>
      </View>

      <TouchableOpacity style={s.saveBtn} onPress={handleSave}>
        <Text style={s.saveBtnText}>Save Preferences</Text>
      </TouchableOpacity>
    </ScrollView>
  );
}

const s = StyleSheet.create({
  container: { flex: 1, backgroundColor: "#0a0e1a" },
  content: { padding: 16, paddingBottom: 40, gap: 20 },
  title: { fontSize: 22, fontWeight: "700", color: "#c8d8f0", marginBottom: 10 },
  section: { gap: 8 },
  sectionTitle: { fontSize: 13, color: "#6a82a8", fontWeight: "600" },
  row: { flexDirection: "row", gap: 8 },
  chip: { flex: 1, height: 38, borderWidth: 1, borderColor: "#1e2d4f", borderRadius: 8, justifyContent: "center", alignItems: "center", backgroundColor: "#0f1628" },
  chipActive: { backgroundColor: "#141d35", borderColor: "#00d4ff" },
  chipText: { fontSize: 12, color: "#6a82a8" },
  chipTextActive: { color: "#00d4ff", fontWeight: "600" },
  input: { height: 46, borderWidth: 1, borderColor: "#1e2d4f", borderRadius: 10, paddingHorizontal: 14, fontSize: 14, backgroundColor: "#0f1628", color: "#c8d8f0" },
  positionRow: { flexDirection: "row", alignItems: "center", backgroundColor: "#0f1628", borderRadius: 10, padding: 14, borderWidth: 1, borderColor: "#1e2d4f" },
  label: { fontSize: 14, color: "#c8d8f0" },
  saveBtn: { height: 46, backgroundColor: "#00d4ff", borderRadius: 10, justifyContent: "center", alignItems: "center", marginTop: 20 },
  saveBtnText: { color: "#000", fontWeight: "700", fontSize: 14 }
});
