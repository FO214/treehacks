//
//  TycoonSceneState.swift
//  treehacks26
//
//  Holds references to the runtime scene (Ground + Tables container + allocator)
//  so we can spawn more tables when agentCount increases without recreating the scene.
//

import RealityKit
import Foundation

@MainActor
final class TycoonSceneState {
    var tablesContainer: Entity?
    var allocator = TableAllocator()
    var lastSpawnedCount = 0

    func ensureTables(count: Int, contentBundle: Bundle) async {
        guard let tables = tablesContainer else { return }
        while allocator.tablesSpawned < count {
            await allocator.spawnNextTable(in: tables, contentBundle: contentBundle)
        }
        lastSpawnedCount = count
    }
}
