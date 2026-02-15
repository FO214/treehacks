//
//  TableAllocator.swift
//  treehacks26
//
//  Tycoon-style: spawns one workspace (table) at a time in a two-row grid.
//  Does not pre-map all slots—allocates next position on demand.
//

import Foundation
import RealityKit
import UIKit

/// Allocates table entities in a 2-row grid. Call `spawnNextTable` each time an agent is added.
final class TableAllocator {
    /// Grid: exactly 2 rows, grow by column (col 0 fills both rows, then col 1, …). Origin = floor/whiteboard ref.
    var tablesSpawned: Int = 0
    let rowCount: Int = 2
    var tableSpacingX: Float = 0.8  // between columns
    var tableSpacingZ: Float = 0.6  // between rows
    var gridOrigin: SIMD3<Float> = .zero

    /// Next slot: column = tablesSpawned / 2, row = tablesSpawned % 2
    func nextGridPosition() -> SIMD3<Float> {
        let col = tablesSpawned / rowCount
        let row = tablesSpawned % rowCount
        let x = gridOrigin.x + Float(col) * tableSpacingX
        let z = gridOrigin.z + Float(row) * tableSpacingZ
        return SIMD3(x, gridOrigin.y, z)
    }

    /// Spawn one more table and add it to `parent`. Returns the new entity, or nil if load failed.
    func spawnNextTable(in parent: Entity, contentBundle: Bundle) async -> Entity? {
        let position = nextGridPosition()
        // Prefer named asset "Office_Props_Pack.usdz" in RealityKitContent
        var tableEntity: Entity?
        if let e = try? await Entity(named: "Office_Props_Pack.usdz", in: contentBundle) { tableEntity = e }
        else if let e = try? await Entity(named: "Office_Props_Pack.usdz", in: contentBundle) { tableEntity = e }
        let entity = tableEntity ?? makePlaceholderTable()
        entity.position = position
        parent.addChild(entity)
        tablesSpawned += 1
        return entity
    }

    /// Simple box placeholder until you add OfficeTable in Reality Composer
    private func makePlaceholderTable() -> Entity {
        let mesh = MeshResource.generateBox(width: 0.6, height: 0.4, depth: 0.4)
        let material = SimpleMaterial(color: .systemBrown, isMetallic: false)
        let model = ModelEntity(mesh: mesh, materials: [material])
        model.name = "Table_\(tablesSpawned)"
        return model
    }
}
