export interface CallgraphLink {
  source: string;
  target: string;
  type?: string;
}

export interface CallgraphNode {
  id: string;
  name: string;
  type?: string;
}

export interface VisualizationAttributes {
  nodeSize: (node: CallgraphNode) => number;
  nodeColor: (node: CallgraphNode) => string;
  nodeLabel: (node: CallgraphNode) => string;
  linkColor: (link: CallgraphLink) => string;
  linkWidth: (link: CallgraphLink) => number;
  linkDashArray: (link: CallgraphLink) => string | null;
}

export class DynamicAttributeProvider {
  static getAttributes(framework: string): VisualizationAttributes {
    // Placeholder implementation
    return {
      nodeSize: (node: CallgraphNode) => 10,
      nodeColor: (node: CallgraphNode) => "#666",
      nodeLabel: (node: CallgraphNode) => node.name,
      linkColor: (link: CallgraphLink) => "#999",
      linkWidth: (link: CallgraphLink) => 1,
      linkDashArray: (link: CallgraphLink) => null,
    };
  }
}