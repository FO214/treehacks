//
//  ImmersiveView.swift
//  treehacks26
//

import SwiftUI
import RealityKit
import ARKit
import RealityKitContent
import UIKit

/// Agent state: thinking → working → testing (then jump + delete).
enum AgentState: String {
    case thinking
    case working
    case testing
}

/// Holds the root anchor entity (invisible), static desks, spawning characters, plane anchor, whiteboard, and cached templates.
@Observable
final class DemoBlockState {
    /// Invisible root entity anchored to surface; children are positioned relative to this.
    var rootEntity: Entity?
    /// Character entities by slot (1-9); desks are static.
    var characterEntities: [Int: Entity] = [:]
    /// Agent state per slot (1-9).
    var agentStates: [Int: AgentState] = [:]
    /// URL for webview above agent when in testing (agent_id -> vercel link).
    var testingWebviewURLs: [Int: String] = [:]
    /// Cached webview attachment entities (populated in make closure).
    var webviewEntities: [Int: Entity] = [:]
    var planeAnchor: AnchorEntity?
    var whiteboardEntity: Entity?
    /// Cached character.usdz; cloned when spawning.
    var characterTemplate: Entity?
    /// Cached computer_desk.usdz; used for static desks.
    var computerDeskTemplate: Entity?
    /// When true, root follows gaze (where user is looking) instead of hand.
    var isRepositioningMode = false
    /// True after we've placed root near user; avoids spawn at plane anchor center (often far away).
    var hasInitialPlacement = false
}

struct ImmersiveView: View {
    @Environment(AppModel.self) private var appModel
    @Environment(\.dismissImmersiveSpace) private var dismissImmersiveSpace
    @State private var blockState = DemoBlockState()
    @State private var handTrackingManager = HandTrackingManager()
    @State private var setupTask: Task<Void, Never>?
    @State private var spawnWebSocketTask: Task<Void, Never>?
    @State private var updateSubscription: EventSubscription?
    @State private var spawnWebSocket: URLSessionWebSocketTask?

    private static let scaleFactor: Float = 12
    private static let maxAgents = 9
    private static let gridCols = 3
    /// Target bounding box size for grid objects (desks/robots).
    private static let targetBoundsSize: Float = 0.06 * scaleFactor
    /// Larger size for desk/table models (Office_Props_Pack).
    private static let deskTargetSize: Float = 0.15 * scaleFactor
    /// Character scale multiplier (characters need to be much larger to be visible).
    private static let characterScaleMultiplier: Float = 3
    /// Extra 2x scale for desks and characters only (not spacing).
    private static let deskAndCharacterSizeMultiplier: Float = 2
    private static let gridSpacing: Float = 0.12 * scaleFactor + 1

    /// 3×3 grid positions (floor of root), row-major order.
    private static var gridPositions: [SIMD3<Float>] {
        let half = Float(gridCols - 1) * gridSpacing / 2
        var positions: [SIMD3<Float>] = []
        for row in 0..<gridCols {
            for col in 0..<gridCols {
                positions.append([
                    Float(col) * gridSpacing - half,
                    targetBoundsSize / 2, // sit on floor
                    Float(row) * gridSpacing - half
                ])
            }
        }
        return positions
    }

    var body: some View {
        RealityView { content, attachments in
            // Root entity: invisible anchor for children, sits on surface
            let root = Entity()
            root.name = "demoRoot"
            root.position = [0, 0.2 * Self.scaleFactor, 0]

            // See-through floor under the root (horizontal XZ plane)
            let floorMesh = MeshResource.generatePlane(width: 0.5 * Self.scaleFactor, height: 0.5 * Self.scaleFactor)
            var floorMat = SimpleMaterial()
            floorMat.color = .init(tint: UIColor.white.withAlphaComponent(0))
            let floorEntity = ModelEntity(mesh: floorMesh, materials: [floorMat])
            floorEntity.name = "floor"
            floorEntity.orientation = simd_quatf(angle: -.pi / 2, axis: [1, 0, 0])  // horizontal
            floorEntity.position = [0, 0, 0]
            root.addChild(floorEntity)

            // Children are spawned when FastAPI sends spawn_agent via WebSocket

            // Plane anchor: snaps to ground (floor) only
            let anchor = AnchorEntity(.plane(.horizontal, classification: .floor, minimumBounds: [0.4 * Self.scaleFactor, 0.4 * Self.scaleFactor]))
            anchor.addChild(root)
            content.add(anchor)

            // Whiteboard: 1.5m closer than before (was 1.2m, now 0.3m in front)
            Task { @MainActor in
                if let whiteboard = try? await Entity(named: "fixed_whiteboard.usdc", in: realityKitContentBundle) {
                    whiteboard.name = "whiteboard"
                    whiteboard.position = [0, 0.5 * Self.scaleFactor, -0.3 * Self.scaleFactor]  // in front of origin
                    anchor.addChild(whiteboard)
                    Self.scaleToBoundsSize(whiteboard, targetSize: Self.targetBoundsSize * 15 / 4)  // 1/4 size
                    blockState.whiteboardEntity = whiteboard

                    // Diagram from project root (diagram.svg → diagram.png), snapped to front of whiteboard
                    let loadDiagram = true
                    if loadDiagram {
                        do {
                            let texture: TextureResource?
                            if let url = Bundle.main.url(forResource: "diagram", withExtension: "png") {
                                texture = try await TextureResource.load(contentsOf: url)
                            } else {
                                texture = try? await TextureResource.load(named: "diagram", in: .main)
                            }
                            if let texture, let diagramPlane = Self.makeDiagramPlane(texture: texture) {
                                diagramPlane.name = "diagram"
                                diagramPlane.position = [0, 0, 0.02 * Self.scaleFactor]  // Slightly in front of whiteboard face
                                whiteboard.addChild(diagramPlane)
                            }
                        } catch {
                            print("[ImmersiveView] Diagram texture load failed: \(error)")
                        }
                    }
                }
            }

            blockState.rootEntity = root
            blockState.characterEntities = [:]
            blockState.planeAnchor = anchor

            // Cache webview attachment entities for testing mode
            for i in 1...Self.maxAgents {
                if let entity = attachments.entity(for: "webview_\(i)") {
                    blockState.webviewEntities[i] = entity
                }
            }

            // Load templates and create 9 static desks (computer on desk)
            Task { @MainActor in
                if let character = try? await Entity(named: "character.usdz", in: realityKitContentBundle) {
                    blockState.characterTemplate = character
                }
                if let computer = try? await Entity(named: "computer_desk.usdz", in: realityKitContentBundle),
                   let root = blockState.rootEntity {
                    // Create 9 static desks at grid positions (never removed)
                    for i in 0..<Self.maxAgents {
                        let desk = computer.clone(recursive: true)
                        desk.name = "desk_\(i)"
                        desk.orientation = simd_quatf(angle: .pi / 2, axis: [0, 1, 0])  // 90° counter clockwise
                        let gridPos = Self.gridPositions[i]
                        desk.position = [gridPos.x, Self.targetBoundsSize / 2 + 1.2 - 0.5, gridPos.z]  // lowered 50cm
                        root.addChild(desk)
                        Self.scaleToBoundsSize(desk, targetSize: Self.targetBoundsSize * Self.deskAndCharacterSizeMultiplier)
                    }
                }
            }

            // Place root near user on surface in front
            // SceneEvents.Update may run off main thread; HandTrackingManager is @MainActor
            updateSubscription = content.subscribe(to: SceneEvents.Update.self) { _ in
                Task { @MainActor in
                    guard let planeAnchor = blockState.planeAnchor else { return }

                    if let deviceAnchor = handTrackingManager.queryDeviceAnchor() {
                        // Device tracking: 45cm in front of user on the surface
                        let t = deviceAnchor.originFromAnchorTransform
                        let devicePos = SIMD3<Float>(t.columns.3.x, t.columns.3.y, t.columns.3.z)
                        let forward = SIMD3<Float>(-t.columns.2.x, -t.columns.2.y, -t.columns.2.z)
                        let horizontalForward = simd_normalize(SIMD3<Float>(forward.x, 0, forward.z))

                        if simd_length(horizontalForward) > 0.1 {
                            // Place center of grid directly in front of user (2m), not at corner
                            let distanceInFront: Float = 2.0
                            let pointInFront = devicePos + horizontalForward * distanceInFront
                            let surfaceY = planeAnchor.position(relativeTo: nil).y
                            let hitWorld = SIMD3<Float>(pointInFront.x, surfaceY, pointInFront.z)

                            // Root: only when initial placement or repositioning (palm open)
                            let shouldUpdateRoot = !blockState.hasInitialPlacement
                                || (blockState.isRepositioningMode && handTrackingManager.isPalmCurrentlyOpen())
                            if shouldUpdateRoot, let root = blockState.rootEntity {
                                let localPos = planeAnchor.convert(position: hitWorld, from: nil)
                                let middleChildCenterOffset: Float = Self.targetBoundsSize / 2
                                root.position = SIMD3<Float>(localPos.x, localPos.y - middleChildCenterOffset, localPos.z)
                                blockState.hasInitialPlacement = true
                            }
                        }
                    } else {
                        // Simulator or no tracking
                        if let root = blockState.rootEntity {
                            root.position = [0, 0, -0.5 * Self.scaleFactor]
                            blockState.hasInitialPlacement = true
                        }
                    }
                }
            }
        } update: { content, attachments in
            // No color updates; models use static usdz appearance
        } attachments: {
            ForEach(1...Self.maxAgents, id: \.self) { agentId in
                Attachment(id: "webview_\(agentId)") {
                    WebView(url: URL(string: blockState.testingWebviewURLs[agentId] ?? "https://google.com"))
                        .frame(width: 400, height: 300)
                        .glassBackgroundEffect()
                }
            }
        }
        .onChange(of: appModel.repositioningMode) { _, newValue in
            blockState.isRepositioningMode = newValue
            handTrackingManager.isRepositioningMode = newValue
        }
        .onAppear {
            blockState.isRepositioningMode = appModel.repositioningMode
            handTrackingManager.isRepositioningMode = appModel.repositioningMode
            startSpawnWebSocket()
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
            updateSubscription?.cancel()
            updateSubscription = nil
            spawnWebSocket?.cancel(with: .goingAway, reason: nil)
            spawnWebSocket = nil
            spawnWebSocketTask?.cancel()
            spawnWebSocketTask = nil
            setupTask?.cancel()
            setupTask = nil
            handTrackingManager.stopTracking()
            handTrackingManager.onOpenPalmDetected = nil
            handTrackingManager.onOpenPalmForDrag = nil
            blockState.rootEntity = nil
            blockState.characterEntities = [:]
            blockState.agentStates = [:]
            blockState.testingWebviewURLs = [:]
            blockState.webviewEntities = [:]
            blockState.planeAnchor = nil
            blockState.whiteboardEntity = nil
            blockState.characterTemplate = nil
            blockState.computerDeskTemplate = nil
            blockState.hasInitialPlacement = false
        }
    }

    /// Creates a plane with diagram texture for the whiteboard front (aspect ~3.22:1 from diagram.svg).
    private static func makeDiagramPlane(texture: TextureResource) -> ModelEntity? {
        let width: Float = 0.8 * Self.scaleFactor
        let height: Float = 0.25 * Self.scaleFactor  // ~3.22:1 aspect
        let mesh = MeshResource.generatePlane(width: width, height: height)
        var mat = SimpleMaterial()
        mat.color = .init(tint: .white, texture: .init(texture))
        return ModelEntity(mesh: mesh, materials: [mat])
    }

    /// Placeholder desk when usdz load fails (visible brown box).
    private static func makePlaceholderDesk() -> Entity {
        let mesh = MeshResource.generateBox(width: 0.06 * Self.scaleFactor, height: 0.06 * Self.scaleFactor, depth: 0.06 * Self.scaleFactor)
        let mat = SimpleMaterial(color: .systemBrown, isMetallic: false)
        return ModelEntity(mesh: mesh, materials: [mat])
    }

    /// Scales an entity so its visual bounding box fits within a cube of the given size.
    /// Falls back to 0.01 if bounds are empty or would produce invisible scale.
    private static func scaleToBoundsSize(_ entity: Entity, targetSize: Float) {
        let bounds = entity.visualBounds(relativeTo: entity)
        let extents = bounds.extents
        let maxExtent = max(extents.x, extents.y, extents.z)
        if maxExtent > 0 {
            let scaleFactor = targetSize / maxExtent
            // Clamp to avoid invisible (too small) or huge models
            let clamped = min(max(scaleFactor, 0.001), 100)
            entity.scale = [clamped, clamped, clamped]
        } else {
            entity.scale = [0.01, 0.01, 0.01]  // fallback for empty bounds
        }
    }

    private func startSpawnWebSocket() {
        guard let url = APIConfig.wsSpawnURL else {
            print("[ImmersiveView] Invalid spawn WebSocket URL")
            return
        }
        spawnWebSocketTask = Task { @MainActor in
            // Brief delay so RealityView has time to create root and load assets
            try? await Task.sleep(for: .seconds(1.5))
            guard !Task.isCancelled else { return }

            let wsTask = URLSession.shared.webSocketTask(with: url)
            spawnWebSocket = wsTask
            wsTask.resume()

            while !Task.isCancelled {
                do {
                    let message = try await wsTask.receive()
                    switch message {
                    case .string(let text):
                        if let data = text.data(using: .utf8),
                           let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                           let type = json["type"] as? String,
                           let agentId = json["agent_id"] as? Int, (1...9).contains(agentId) {
                            switch type {
                            case "create_agent_thinking":
                                await handleCreateAgentThinking(agentId: agentId, taskName: json["task_name"] as? String ?? "")
                            case "agent_start_working":
                                await handleAgentStartWorking(agentId: agentId)
                            case "agent_start_testing":
                                let vercel = json["vercel_link"] as? String ?? ""
                                let browserbase = json["browserbase_link"] as? String ?? ""
                                await handleAgentStartTesting(agentId: agentId, vercelLink: vercel, browserbaseLink: browserbase)
                            default:
                                break
                            }
                        }
                    case .data:
                        break
                    @unknown default:
                        break
                    }
                } catch {
                    if !Task.isCancelled {
                        print("[ImmersiveView] Spawn WebSocket error: \(error)")
                    }
                    break
                }
            }
        }
    }

    private func handleCreateAgentThinking(agentId: Int, taskName: String) async {
        await MainActor.run {
            guard let root = blockState.rootEntity else { return }

            // Remove existing character at this slot if any
            if let existing = blockState.characterEntities[agentId] {
                existing.removeFromParent()
                blockState.characterEntities.removeValue(forKey: agentId)
            }

            let gridIndex = agentId - 1
            let character: Entity
            if let template = blockState.characterTemplate {
                character = template.clone(recursive: true)
                let baseSize = Self.deskTargetSize * Self.characterScaleMultiplier * Self.deskAndCharacterSizeMultiplier
                Self.scaleToBoundsSize(character, targetSize: baseSize / 4)
            } else {
                character = Self.makePlaceholderDesk()
            }
            character.name = "character_\(agentId)"
            character.orientation = simd_quatf(angle: 70 * .pi / 180, axis: [0, 1, 0])
            let gridPos = Self.gridPositions[gridIndex]
            let targetY = Self.targetBoundsSize / 2 + 1.2 - 0.5
            // Start 1m below, then smooth jump up to final position
            character.position = [gridPos.x, targetY - 1.0, gridPos.z - 1.0]
            root.addChild(character)
            blockState.characterEntities[agentId] = character
            blockState.agentStates[agentId] = .thinking

            var targetTransform = character.transform
            targetTransform.translation = [gridPos.x, targetY, gridPos.z - 1.0]
            character.move(to: targetTransform, relativeTo: root, duration: 0.6, timingFunction: .easeOut)
        }
    }

    private func handleAgentStartWorking(agentId: Int) async {
        await MainActor.run {
            blockState.agentStates[agentId] = .working
        }
    }

    private func handleAgentStartTesting(agentId: Int, vercelLink: String, browserbaseLink: String) async {
        await MainActor.run {
            blockState.agentStates[agentId] = .testing
            guard let character = blockState.characterEntities[agentId] else { return }

            // Show webview above agent (vercel link)
            blockState.testingWebviewURLs[agentId] = vercelLink
            if let webviewEntity = blockState.webviewEntities[agentId] {
                webviewEntity.removeFromParent()
                webviewEntity.position = [0, 1.5, 0]  // 1.5m above character
                character.addChild(webviewEntity)
            }

            // Smooth jump 1m upward, then delete
            let currentTransform = character.transform
            var targetTransform = currentTransform
            targetTransform.translation.y += 1.0  // 1m up

            character.move(to: targetTransform, relativeTo: character.parent, duration: 0.8, timingFunction: .easeOut)

            Task { @MainActor in
                try? await Task.sleep(for: .seconds(0.9))  // Wait for animation
                character.removeFromParent()
                blockState.characterEntities.removeValue(forKey: agentId)
                blockState.agentStates.removeValue(forKey: agentId)
                blockState.testingWebviewURLs.removeValue(forKey: agentId)
            }
        }
    }

    private func setupHandTracking() {
        handTrackingManager.onOpenPalmDetected = {
            await triggerRecordOnce()
        }

        // Repositioning is now gaze-based (see SceneEvents.Update subscription)
        handTrackingManager.onOpenPalmForDrag = { _ in }

        Task {
            await handTrackingManager.startTracking()
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
