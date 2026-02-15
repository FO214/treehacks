//
//  AppModel.swift
//  treehacks26
//
//  Created by Rachel Zhang on 2026-02-14.
//

import SwiftUI

/// Maintains app-wide state (tycoon: 1 agent = 1 workspace, spawn tables as agents grow)
@MainActor
@Observable
class AppModel {
    let immersiveSpaceID = "ImmersiveSpace"
    enum ImmersiveSpaceState {
        case closed
        case inTransition
        case open
    }
    var immersiveSpaceState = ImmersiveSpaceState.closed

    /// Number of agents; should match number of tables (start 1, +1 per new agent)
    var agentCount: Int = 1

    func addAgent() {
        agentCount += 1
    }
}
