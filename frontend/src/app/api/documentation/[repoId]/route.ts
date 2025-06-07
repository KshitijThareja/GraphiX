import { NextRequest, NextResponse } from 'next/server';

export async function GET(
  request: NextRequest,
  { params }: { params: { repoId: string } }
) {
  try {
    const repoId = params.repoId;
    console.log('API route GET /api/documentation/[repoId] called with repoId:', repoId);
    
    // Get the backend URL from environment variable or use a default
    const backendUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
    const apiUrl = `${backendUrl}/documentation/${repoId}`;
    
    console.log('Requesting documentation from backend at:', apiUrl);
    
    // Make request to backend
    const response = await fetch(apiUrl, {
      headers: {
        'Content-Type': 'application/json',
      },
      cache: 'no-store',
    });

    if (!response.ok) {
      const errorText = await response.text();
      console.error(`Backend error (${response.status}):`, errorText);
      throw new Error(`Backend returned ${response.status}: ${errorText}`);
    }

    const data = await response.json();
    console.log('Backend documentation response:', JSON.stringify(data).substring(0, 200) + '...');
    
    // Transform the data into a tree structure for the DocumentationTree component
    const treeData = transformToTreeStructure(data.documentation || {});
    console.log(`Transformed ${treeData.length} root documentation items`);
    
    return NextResponse.json({ 
      documentation: treeData,
      status: data.status,
      generated_at: data.generated_at,
    });
  } catch (error) {
    console.error('Error fetching documentation:', error);
    return NextResponse.json(
      { error: error instanceof Error ? error.message : 'Unknown error' },
      { status: 500 }
    );
  }
}

function transformToTreeStructure(documentation: any) {
  console.log('TransformToTreeStructure called with:', typeof documentation);
  
  // Handle different possible input formats
  if (!documentation) {
    console.warn('Documentation is null or undefined');
    return [];
  }
  
  if (Array.isArray(documentation)) {
    console.log('Documentation is already an array with', documentation.length, 'items');
    return documentation.map(item => transformDocItem(item));
  }
  
  // Handle normal case with modules, classes, functions
  const { modules = [], classes = [], functions = [] } = documentation;
  console.log(`Documentation contains: ${modules.length} modules, ${classes.length} classes, ${functions.length} functions`);
  
  // Create a map of module names to module objects
  const moduleMap = new Map();
  
  // Process modules
  const rootItems: any[] = [];
  
  modules.forEach((module: any) => {
    const moduleItem = {
      id: module.qualified_name || `module_${module.name}`,
      name: module.name || module.qualified_name?.split('.').pop() || 'Unknown Module',
      type: 'module',
      children: [],
      docstring: module.docstring || '',
      signature: module.signature || module.qualified_name || '',
    };
    
    moduleMap.set(moduleItem.id, moduleItem);
    rootItems.push(moduleItem);
  });
  
  // Process classes and add them to their parent modules
  classes.forEach((cls: any) => {
    if (!cls.qualified_name) {
      console.warn('Class without qualified_name:', cls);
      return;
    }
    
    const parts = cls.qualified_name.split('.');
    const className = parts.pop() || cls.name || 'Unknown Class';
    const moduleName = parts.join('.');
    
    const classItem = {
      id: cls.qualified_name,
      name: cls.name || className,
      type: 'class',
      children: [],
      docstring: cls.docstring || '',
      signature: cls.signature || cls.qualified_name || '',
      decorators: cls.decorators || [],
      parameters: cls.parameters || [],
      returns: cls.returns || {},
    };
    
    const parentModule = moduleMap.get(moduleName);
    if (parentModule) {
      parentModule.children.push(classItem);
    } else {
      rootItems.push(classItem);
    }
  });
  
  // Process functions and add them to their parent modules or classes
  functions.forEach((func: any) => {
    if (!func.qualified_name) {
      console.warn('Function without qualified_name:', func);
      return;
    }
    
    const parts = func.qualified_name.split('.');
    const funcName = parts.pop() || func.name || 'Unknown Function';
    const parentName = parts.join('.');
    
    const funcItem = {
      id: func.qualified_name,
      name: func.name || funcName,
      type: func.is_method ? 'method' : 'function',
      docstring: func.docstring || '',
      signature: func.signature || func.qualified_name || '',
      decorators: func.decorators || [],
      parameters: func.parameters || [],
      returns: func.returns || {},
    };
    
    const parentModule = moduleMap.get(parentName);
    if (parentModule) {
      parentModule.children.push(funcItem);
    } else {
      // Check if it's a method in a class
      let found = false;
      for (const module of rootItems) {
        if (module.children) {
          const parentClass = module.children.find((c: any) => c.id === parentName);
          if (parentClass) {
            parentClass.children.push(funcItem);
            found = true;
            break;
          }
        }
      }
      
      // If no parent found, add to root
      if (!found) {
        rootItems.push(funcItem);
      }
    }
  });
  
  return rootItems;
}

// Helper function to transform a single documentation item
function transformDocItem(item: any) {
  // Simple pass-through for already formatted items
  if (item.id && item.name && item.type) {
    return item;
  }
  
  // Transform a backend item to frontend format
  return {
    id: item.qualified_name || item.id || `item_${Math.random().toString(36).substring(2, 9)}`,
    name: item.name || item.qualified_name?.split('.').pop() || 'Unknown Item',
    type: item.type || (item.is_method ? 'method' : 'function'),
    children: [],
    docstring: item.docstring || '',
    signature: item.signature || item.qualified_name || '',
    decorators: item.decorators || [],
    parameters: item.parameters || [],
    returns: item.returns || {},
  };
}

export async function POST(
  request: NextRequest,
  { params }: { params: { repoId: string } }
) {
  try {
    const repoId = params.repoId;
    const body = await request.json();
    
    // Get the backend URL from environment variable or use a default
    const backendUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
    
    // Make request to backend
    const response = await fetch(`${backendUrl}/documentation/generate`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        repository_id: repoId,
        framework_hint: body.framework_hint,
        include_docstring_generation: body.include_docstring_generation || true,
      }),
    });

    if (!response.ok) {
      throw new Error(`Backend returned ${response.status}: ${await response.text()}`);
    }

    const data = await response.json();
    
    return NextResponse.json(data);
  } catch (error) {
    console.error('Error generating documentation:', error);
    return NextResponse.json(
      { error: error instanceof Error ? error.message : 'Unknown error' },
      { status: 500 }
    );
  }
}
