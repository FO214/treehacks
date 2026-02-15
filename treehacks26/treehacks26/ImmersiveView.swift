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
    @Environment(\.dismissImmersiveSpace) private var dismissImmersiveSpace
    @State private var boxColor: UIColor = .systemRed
    @State private var blockState = DemoBlockState()
    @State private var handTrackingManager = HandTrackingManager()
    @State private var wsTask: URLSessionWebSocketTask?
    @State private var setupTask: Task<Void, Never>?

    var body: some View {
        // IMPORTANT: Initial closure must NOT capture boxColor. If it does, SwiftUI may
        // recreate the entire RealityView when boxColor changes, causing the box to disappear briefly.
        RealityView { content in
            // Create a box in front of the user
            let box = MeshResource.generateBox(size: [0.4, 0.4, 0.4])
            let material = SimpleMaterial(color: .systemRed, isMetallic: false)
            let entity = ModelEntity(mesh: box, materials: [material])
            entity.name = "demoBlock"

            // World anchor: shows immediately (no head-tracking wait). Box at 1.2m in front of origin.
            var transform = matrix_identity_float4x4
            transform.columns.3 = SIMD4<Float>(0, 0, -1.2, 1)
            let anchor = AnchorEntity(.world(transform: transform))
            anchor.addChild(entity)
            content.add(anchor)

            blockState.entity = entity
        } update: { _ in
            guard let entity = blockState.entity else { return }
            guard var modelComponent = entity.components[ModelComponent.self] else { return }
            let newMaterial = SimpleMaterial(color: boxColor, isMetallic: false)
            modelComponent.materials = [newMaterial]
            entity.components[ModelComponent.self] = modelComponent
        }
        .overlay(alignment: .topLeading) {
            Button {
                Task { @MainActor in
                    appModel.immersiveSpaceState = .inTransition
                    await dismissImmersiveSpace()
                }
            } label: {
                Label("Exit", systemImage: "xmark.circle.fill")
            }
            .buttonStyle(.borderedProminent)
            .padding(24)
        }
        .onAppear {
            startWebSocket()
            // Defer hand tracking so the box renders first (ARKit session can delay initial render)
            setupTask = Task {
                try? await Task.sleep(for: .seconds(1.5))
                guard !Task.isCancelled else { return }
                setupHandTracking()
            }
        }
        .onDisappear {
            setupTask?.cancel()
            setupTask = nil
            wsTask?.cancel(with: .goingAway, reason: nil)
            wsTask = nil
            handTrackingManager.stopTracking()
            blockState.entity = nil
        }
    }

    private func startWebSocket() {
        guard let url = APIConfig.wsDemoURL else {
            print("[Demo] Invalid WebSocket URL")
            return
        }
        let task = URLSession.shared.webSocketTask(with: url)
        wsTask = task
        task.resume()
        receiveColor()
    }

    private func receiveColor() {
        wsTask?.receive { result in
            switch result {
            case .success(let message):
                switch message {
                case .string(let text):
                    if let data = text.data(using: .utf8),
                       let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                       let r = json["r"] as? Int,
                       let g = json["g"] as? Int,
                       let b = json["b"] as? Int {
                        let color = UIColor(
                            red: CGFloat(r) / 255,
                            green: CGFloat(g) / 255,
                            blue: CGFloat(b) / 255,
                            alpha: 1
                        )
                        Task { @MainActor in
                            boxColor = color
                        }
                    }
                case .data:
                    break
                @unknown default:
                    break
                }
                receiveColor() // continue receiving
            case .failure(let error):
                print("[Demo] WebSocket error: \(error.localizedDescription)")
                // Reconnect after delay
                Task { @MainActor in
                    try? await Task.sleep(for: .seconds(2))
                    guard wsTask != nil else { return }
                    startWebSocket()
                }
            }
        }
    }

    private func setupHandTracking() {
        handTrackingManager.onOpenPalmDetected = {
            await sendGestureToServer("open_palm")
            await triggerRecordOnce()
        }

        Task {
            await handTrackingManager.startTracking()
        }
    }

    private func sendGestureToServer(_ gesture: String) {
        let msg: [String: Any] = ["type": "gesture", "gesture": gesture]
        guard let data = try? JSONSerialization.data(withJSONObject: msg),
              let text = String(data: data, encoding: .utf8) else { return }
        wsTask?.send(.string(text)) { error in
            if let error { print("[Demo] WebSocket send failed: \(error)") }
        }
    }

    private func triggerRecordOnce() async {
        // Call record-once (proxied via FastAPI to voice server)
        guard let url = URL(string: "\(APIConfig.baseURL)/record-once") else {
            print("[HandTracking] Invalid voice server URL")
            return
        }

        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.timeoutInterval = 15
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
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
