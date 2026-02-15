//
//  ImmersiveView.swift
//  treehacks26
//

import SwiftUI
import RealityKit

/// Holds the demo block entity so we can update its material when value changes.
@Observable
final class DemoBlockState {
    var entity: ModelEntity?
}

struct ImmersiveView: View {
    @Environment(AppModel.self) private var appModel
    @State private var demoValue: Int = 0
    @State private var blockState = DemoBlockState()
    @State private var handTrackingManager = HandTrackingManager()

    var body: some View {
        RealityView { content in
            // Create a box 1m in front of the user, ~eye level
            let box = MeshResource.generateBox(size: [0.3, 0.3, 0.3])
            let material = SimpleMaterial(color: colorForValue(demoValue), isMetallic: false)
            let entity = ModelEntity(mesh: box, materials: [material])
            entity.name = "demoBlock"

            let anchor = AnchorEntity(world: SIMD3<Float>(0, 0, -1.2))
            anchor.addChild(entity)
            content.add(anchor)

            blockState.entity = entity
        } update: { _ in
            guard let entity = blockState.entity else { return }
            guard var modelComponent = entity.components[ModelComponent.self] else { return }
            let newMaterial = SimpleMaterial(color: colorForValue(demoValue), isMetallic: false)
            modelComponent.materials = [newMaterial]
            entity.components[ModelComponent.self] = modelComponent
        }
        .onAppear {
            startPolling()
            setupHandTracking()
        }
        .onDisappear {
            handTrackingManager.stopTracking()
        }
    }

    private func colorForValue(_ value: Int) -> UIColor {
        value == 1 ? .systemGreen : .systemRed
    }

    private func startPolling() {
        Task {
            while true {
                await fetchDemoValue()
                try? await Task.sleep(for: .seconds(2))
            }
        }
    }

    private func fetchDemoValue() async {
        guard let url = URL(string: "\(APIConfig.baseURL)/demo/value") else { return }
        var request = URLRequest(url: url)
        request.setValue("true", forHTTPHeaderField: "ngrok-skip-browser-warning")
        do {
            let (data, _) = try await URLSession.shared.data(for: request)
            if let json = try JSONSerialization.jsonObject(with: data) as? [String: Any],
               let value = json["value"] as? Int {
                await MainActor.run {
                    demoValue = value
                }
            }
        } catch {
            // Silently ignore network errors (e.g. backend not running)
        }
    }

    private func setupHandTracking() {
        handTrackingManager.onOpenPalmDetected = {
            await triggerRecordOnce()
        }

        Task {
            await handTrackingManager.startTracking()
        }
    }

    private func triggerRecordOnce() async {
        // Call the voice server's record-once endpoint
        guard let url = URL(string: "\(APIConfig.voiceServerURL)/record-once") else {
            print("[HandTracking] Invalid voice server URL")
            return
        }

        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("true", forHTTPHeaderField: "ngrok-skip-browser-warning")
        request.httpBody = "{}".data(using: .utf8)

        do {
            let (data, response) = try await URLSession.shared.data(for: request)
            if let httpResponse = response as? HTTPURLResponse {
                print("[HandTracking] record-once response: \(httpResponse.statusCode)")
            }
            if let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
                print("[HandTracking] record-once result: \(json)")
            }
        } catch {
            print("[HandTracking] record-once failed: \(error)")
        }
    }
}

#Preview(immersionStyle: .mixed) {
    ImmersiveView()
        .environment(AppModel())
}
