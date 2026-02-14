//
//  ContentView.swift
//  OctaviusApp
//
//  Created by Rachel Zhang on 2025-02-15.
//

import SwiftUI
import RealityKit
import RealityKitContent
import ARKit

struct ContentView: View {
    @State private var isButtonVisible = true
    
    var body: some View {
        VStack {
            Text("Select objects to activate arm motion")
                .font(.title2)
                .foregroundColor(.white)
                .padding()
                .background(Color.black.opacity(0.7))
                .cornerRadius(10)
                .padding(.bottom, 20)
            
            if isButtonVisible {
                Circle()
                    .frame(width: 100, height: 100)
                    .foregroundColor(.blue)
                    .focused($isFocused)
                    .gesture(
                        SpatialTapGesture().onEnded { _ in
                            isButtonVisible = false // Disappear on pinch
                        }
                    )
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
    
    @FocusState private var isFocused: Bool
}

#Preview {
    ContentView()
}
