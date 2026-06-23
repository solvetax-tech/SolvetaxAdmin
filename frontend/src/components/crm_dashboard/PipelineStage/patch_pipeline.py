import os

filepath = r'c:\Users\reshm\OneDrive\Desktop\solvetaxx\solvetax_frontend\app\src\components\crm_dashboard\PipelineStage\PipelineStages.jsx'

with open(filepath, 'r', encoding='utf-8') as f:
    content = f.read()

if 'return (' in content and '<div className="pipeline-module-container">' in content:
    print("Found return and container. Attempting structural move...")
    
    content = content.replace('  return (', '  return (\n    <>')
    content = content.replace('<div className="pipeline-module-container">', '      <div className="pipeline-module-container">')
    
    # We need to find the specific closing line of pipeline-module-container
    # It's usually right before {isFilterOpen
    content = content.replace('      {isFilterOpen && (', '      </div>\n\n      {isFilterOpen && (')
    
    # And fix the end
    content = content.replace('    </div>\n  );', '    </>\n  );')

with open(filepath, 'w', encoding='utf-8') as f:
    f.write(content)

print("Successfully move drawers in PipelineStages.jsx")
