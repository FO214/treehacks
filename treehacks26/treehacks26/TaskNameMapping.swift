//
//  TaskNameMapping.swift
//  treehacks26
//

import Foundation

/// Maps task name strings to (x, y) coordinates on a 1920×1080 display.
/// Coordinates are in pixels; origin (0,0) is top-left.
let taskNameToPosition: [String: (x: Int, y: Int)] = [
    "placeholder task": (960, 540),  // center of 1920×1080
]
