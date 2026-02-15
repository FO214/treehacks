//
//  ImmersiveView.swift
//  treehacks26
//

import SwiftUI
import RealityKit
import ARKit

/// Holds the root anchor entity (invisible), child cube entities, and plane anchor.
@Observable
final class DemoBlockState {
    /// Invisible root entity anchored to surface; children are positioned relative to this.
    var rootEntity: Entity?
    /// Child cubes in a grid; these are the ones that cycle color.
    var childEntities: [ModelEntity] = []
    var planeAnchor: AnchorEntity?
    /// When true, root follows gaze (where user is looking) instead of hand.
    var isRepositioningMode = false
}

struct ImmersiveView: View {
    @Environment(AppModel.self) private var appModel
    @Environment(\.dismissImmersiveSpace) private var dismissImmersiveSpace
    @State private var boxColor: UIColor = .systemRed
    @State private var blockState = DemoBlockState()
    @State private var handTrackingManager = HandTrackingManager()
    @State private var wsTask: URLSessionWebSocketTask?
    @State private var setupTask: Task<Void, Never>?
    @State private var spawnTask: Task<Void, Never>?

    private static let maxAgents = 9
    private static let gridCols = 3
    private static let cubeSize: Float = 0.06
    private static let gridSpacing: Float = 0.08

    /// 3×3 grid positions (floor of root), row-major order.
    private static var gridPositions: [SIMD3<Float>] {
        let half = Float(gridCols - 1) * gridSpacing / 2
        var positions: [SIMD3<Float>] = []
        for row in 0..<gridCols {
            for col in 0..<gridCols {
                positions.append([
                    Float(col) * gridSpacing - half,
                    cubeSize / 2, // sit on floor
                    Float(row) * gridSpacing - half
                ])
            }
        }
        return positions
    }

    var body: some View {
        // IMPORTANT: Initial closure must NOT capture boxColor. If it does, SwiftUI may
        // recreate the entire RealityView when boxColor changes, causing the box to disappear briefly.
        RealityView { content in
            // Root entity: invisible anchor for children, sits on surface (no mesh)
            let root = Entity()
            root.name = "demoRoot"
            root.position = [0, 0.2, 0]

            // Children are spawned one per second by spawnTask (max 9, then reset)

            // Plane anchor: snaps to nearest horizontal surface (table, floor, etc.)
            let anchor = AnchorEntity(.plane(.horizontal, classification: .any, minimumBounds: [0.4, 0.4]))
            anchor.addChild(root)
            content.add(anchor)

            blockState.rootEntity = root
            blockState.childEntities = []
            blockState.planeAnchor = anchor

            // Gaze-based repositioning: project surface where user is looking
            _ = content.subscribe(to: SceneEvents.Update.self) { _ in
                guard blockState.isRepositioningMode,
                      let root = blockState.rootEntity,
                      let planeAnchor = blockState.planeAnchor,
                      let deviceAnchor = handTrackingManager.queryDeviceAnchor() else { return }

                let t = deviceAnchor.originFromAnchorTransform
                let devicePos = SIMD3<Float>(t.columns.3.x, t.columns.3.y, t.columns.3.z)
                // Forward = -Z in camera space
                let forward = SIMD3<Float>(-t.columns.2.x, -t.columns.2.y, -t.columns.2.z)
                let forwardNorm = simd_normalize(forward)

                // Project gaze ray onto horizontal surface ~0.5m below head (table height)
                let surfaceY = devicePos.y - 0.5
                let planeNormal = SIMD3<Float>(0, 1, 0)
                let denom = simd_dot(forwardNorm, planeNormal)
                guard abs(denom) > 0.01 else { return } // avoid parallel
                let tHit = (surfaceY - devicePos.y) / denom
                guard tHit > 0.1, tHit < 5.0 else { return } // 0.1m–5m in front
                let hitWorld = devicePos + forwardNorm * tHit

                let localPos = planeAnchor.convert(position: hitWorld, from: nil)
                root.position = SIMD3<Float>(localPos.x, 0.2, localPos.z)
            }
        } update: { _ in
            let newMaterial = SimpleMaterial(color: boxColor, isMetallic: false)
            for entity in blockState.childEntities {
                guard var modelComponent = entity.components[ModelComponent.self] else { continue }
                modelComponent.materials = [newMaterial]
                entity.components[ModelComponent.self] = modelComponent
            }
        }
        .onChange(of: appModel.repositioningMode) { _, newValue in
            blockState.isRepositioningMode = newValue
            handTrackingManager.isRepositioningMode = newValue
        }
        .onAppear {
            blockState.isRepositioningMode = appModel.repositioningMode
            handTrackingManager.isRepositioningMode = appModel.repositioningMode
            startWebSocket()
            startSpawnLoop()
            // Defer hand tracking so the box renders first (ARKit session can delay initial render)
            // Skip on simulator: hand tracking is not supported and produces "not authorized" errors
            #if !targetEnvironment(simulator)
            setupTask = Task {
                try? await Task.sleep(for: .seconds(2.0))
                guard !Task.isCancelled else { return }
                setupHandTracking()
            }
            #endif
        }
        .onDisappear {
            spawnTask?.cancel()
            spawnTask = nil
            setupTask?.cancel()
            setupTask = nil
            wsTask?.cancel(with: .goingAway, reason: nil)
            wsTask = nil
            handTrackingManager.stopTracking()
            blockState.rootEntity = nil
            blockState.childEntities = []
            blockState.planeAnchor = nil
        }
    }

    private func startSpawnLoop() {
        spawnTask = Task { @MainActor in
            // Brief delay so RealityView has time to create root
            try? await Task.sleep(for: .seconds(0.5))
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(1))
                guard !Task.isCancelled else { return }
                guard let root = blockState.rootEntity else { continue }

                let count = blockState.childEntities.count
                if count >= Self.maxAgents {
                    // Remove all children and reset
                    for child in blockState.childEntities {
                        child.removeFromParent()
                    }
                    blockState.childEntities = []
                } else {
                    // Add one agent at the next grid spot
                    let pos = Self.gridPositions[count]
                    let mesh = MeshResource.generateBox(size: [Self.cubeSize, Self.cubeSize, Self.cubeSize])
                    let material = SimpleMaterial(color: boxColor, isMetallic: false)
                    let child = ModelEntity(mesh: mesh, materials: [material])
                    child.name = "agent_\(count)"
                    child.position = pos
                    root.addChild(child)
                    blockState.childEntities.append(child)
                }
            }
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

        // Repositioning is now gaze-based (see SceneEvents.Update subscription)
        handTrackingManager.onOpenPalmForDrag = { _ in }

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
