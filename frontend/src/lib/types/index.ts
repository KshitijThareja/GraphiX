export interface CallgraphNode {
    id: string;
    group: number;
    type: 'function' | 'method' | 'class' | 'module';
    complexity: number;
    file?: string;
    className?: string;
    metadata?: {
      parameters?: string[];
      returns?: string;
      docstring?: string;
      decorators?: string[];
      http_methods?: string[];
      security?: string[];
      refactoring?: string;
    };
  }
  
  export interface CallgraphLink {
    source: string;
    target: string;
    value?: number;
    type?: 'call' | 'inheritance' | 'import' | 'dependency';
    metadata?: {
      line_number?: number;
      context?: string;
      is_dynamic?: boolean;
    };
  }
  
  export interface CallgraphData {
    nodes: CallgraphNode[];
    links: CallgraphLink[];
    classes?: string[];
    imports?: Record<string, string[]>;
    metadata?: {
      repo_url?: string;
      analysis_date?: string;
      language?: string;
      framework?: string;
      stats?: {
        total_nodes: number;
        total_links: number;
        avg_complexity: number;
        most_complex_node?: string;
      };
    };
  }
  
  export interface CallgraphVisualizationConfig {
    nodeColorScheme?: 'group' | 'complexity' | 'type';
    linkColorScheme?: 'type' | 'value';
    showNodeLabels?: boolean;
    showTooltips?: boolean;
    physics?: {
      repulsion?: number;
      gravity?: number;
      linkDistance?: number;
    };
  }
  
  export interface EnrichedCallgraphNode extends CallgraphNode {
    llm_analysis?: {
      purpose?: string;
      quality_metrics?: {
        cohesion?: number;
        coupling?: number;
        readability?: number;
      };
      suggestions?: {
        refactoring?: string[];
        documentation?: string[];
      };
    };
  }