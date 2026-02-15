//
//  ImmersiveView.swift
//  treehacks26
//

import SwiftUI
import RealityKit
import ARKit
import RealityKitContent

/// Holds the root anchor entity (invisible), static desks, spawning characters, plane anchor, whiteboard, and cached templates.
@Observable
final class DemoBlockState {
    /// Invisible root entity anchored to surface; children are positioned relative to this.
    var rootEntity: Entity?
    /// Character entities only (spawn/despawn); desks are static.
    var characterEntities: [Entity] = []
    var planeAnchor: AnchorEntity?
    var whiteboardEntity: Entity?
    /// Cached complete.usdz (characters); cloned when spawning.
    var completeTemplate: Entity?
    /// Cached computerSpawn.usdz (computer on desk); used for static desks.
    var computerSpawnTemplate: Entity?
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
    @State private var spawnTask: Task<Void, Never>?

    private static let maxAgents = 9
    private static let gridCols = 3
    /// Target bounding box size for grid objects (desks/robots).
    private static let targetBoundsSize: Float = 0.06
    /// Larger size for desk/table models (Office_Props_Pack).
    private static let deskTargetSize: Float = 0.15
    private static let gridSpacing: Float = 0.12

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
        RealityView { content in
            // Root entity: invisible anchor for children, sits on surface
            let root = Entity()
            root.name = "demoRoot"
            root.position = [0, 0.2, 0]

            // Black floor under the root (horizontal XZ plane)
            let floorMesh = MeshResource.generatePlane(width: 0.5, height: 0.5)
            var floorMat = SimpleMaterial()
            floorMat.color = .init(tint: .black)
            let floorEntity = ModelEntity(mesh: floorMesh, materials: [floorMat])
            floorEntity.name = "floor"
            floorEntity.orientation = simd_quatf(angle: -.pi / 2, axis: [1, 0, 0])  // horizontal
            floorEntity.position = [0, 0, 0]
            root.addChild(floorEntity)

            // Children are spawned one per second by spawnTask (max 9, then reset)

            // Plane anchor: snaps to nearest horizontal surface (table, floor, etc.)
            let anchor = AnchorEntity(.plane(.horizontal, classification: .table, minimumBounds: [0.4, 0.4]))
            anchor.addChild(root)
            content.add(anchor)

            // Whiteboard: farther from user (1.2m in front), loaded from usdz
            Task { @MainActor in
                if let whiteboard = try? await Entity(named: "fixed_whiteboard.usdc", in: realityKitContentBundle) {
                    whiteboard.name = "whiteboard"
                    whiteboard.position = [0, 0.5, -1.2]  // 1.2m in front of origin
                    anchor.addChild(whiteboard)
                    Self.scaleToBoundsSize(whiteboard, targetSize: Self.targetBoundsSize * 5)
                    blockState.whiteboardEntity = whiteboard
                }
            }

            blockState.rootEntity = root
            blockState.characterEntities = []
            blockState.planeAnchor = anchor

            // Load templates and create 9 static desks (computer on desk)
            Task { @MainActor in
                if let complete = try? await Entity(named: "complete.usdz", in: realityKitContentBundle) {
                    blockState.completeTemplate = complete
                }
                if let computer = try? await Entity(named: "computerSpawn.usdz", in: realityKitContentBundle),
                   let root = blockState.rootEntity {
                    // Create 9 static desks at grid positions (never removed)
                    for i in 0..<Self.maxAgents {
                        let desk = computer.clone(recursive: true)
                        desk.name = "desk_\(i)"
                        let gridPos = Self.gridPositions[i]
                        desk.position = [gridPos.x, Self.targetBoundsSize / 2, gridPos.z]
                        root.addChild(desk)
                        Self.scaleToBoundsSize(desk, targetSize: Self.targetBoundsSize)
                    }
                }
            }

            // Place root near user on surface in front
            _ = content.subscribe(to: SceneEvents.Update.self) { _ in
                guard let planeAnchor = blockState.planeAnchor else { return }

                if let deviceAnchor = handTrackingManager.queryDeviceAnchor() {
                    // Device tracking: 45cm in front of user on the surface
                    let t = deviceAnchor.originFromAnchorTransform
                    let devicePos = SIMD3<Float>(t.columns.3.x, t.columns.3.y, t.columns.3.z)
                    let forward = SIMD3<Float>(-t.columns.2.x, -t.columns.2.y, -t.columns.2.z)
                    let horizontalForward = simd_normalize(SIMD3<Float>(forward.x, 0, forward.z))

                    if simd_length(horizontalForward) > 0.1 {
                        let point45cmOut = devicePos + horizontalForward * 0.45
                        let surfaceY = planeAnchor.position(relativeTo: nil).y
                        let hitWorld = SIMD3<Float>(point45cmOut.x, surfaceY, point45cmOut.z)

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
                        root.position = [0, 0, -0.5]
                        blockState.hasInitialPlacement = true
                    }
                }
            }
        } update: { _ in
            // No color updates; models use static usdz appearance
        }
        .onChange(of: appModel.repositioningMode) { _, newValue in
            blockState.isRepositioningMode = newValue
            handTrackingManager.isRepositioningMode = newValue
        }
        .onAppear {
            blockState.isRepositioningMode = appModel.repositioningMode
            handTrackingManager.isRepositioningMode = appModel.repositioningMode
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
            handTrackingManager.stopTracking()
            blockState.rootEntity = nil
            blockState.characterEntities = []
            blockState.planeAnchor = nil
            blockState.whiteboardEntity = nil
            blockState.completeTemplate = nil
            blockState.computerSpawnTemplate = nil
            blockState.hasInitialPlacement = false
        }
    }

    /// Placeholder desk when usdz load fails (visible brown box).
    private static func makePlaceholderDesk() -> Entity {
        let mesh = MeshResource.generateBox(width: 0.06, height: 0.06, depth: 0.06)
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
            let clamped = min(max(scaleFactor, 0.001), 10)
            entity.scale = [clamped, clamped, clamped]
        } else {
            entity.scale = [0.01, 0.01, 0.01]  // fallback for empty bounds
        }
    }

    private func startSpawnLoop() {
        spawnTask = Task { @MainActor in
            // Brief delay so RealityView has time to create root and load complete.usdz
            try? await Task.sleep(for: .seconds(1.5))
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(1))
                guard !Task.isCancelled else { return }
                guard let root = blockState.rootEntity else { continue }

                let count = blockState.characterEntities.count
                if count >= Self.maxAgents {
                    // Remove all characters and reset (desks stay)
                    for character in blockState.characterEntities {
                        character.removeFromParent()
                    }
                    blockState.characterEntities = []
                } else {
                    // Spawn one character at the next grid spot
                    let character: Entity
                    if let template = blockState.completeTemplate {
                        character = template.clone(recursive: true)
                        Self.scaleToBoundsSize(character, targetSize: Self.deskTargetSize)
                    } else {
                        character = Self.makePlaceholderDesk()
                    }
                    character.name = "character_\(count)"
                    let gridPos = Self.gridPositions[count]
                    character.position = [gridPos.x, Self.deskTargetSize / 2, gridPos.z]
                    root.addChild(character)
                    blockState.characterEntities.append(character)
                }
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
