// PENDING / NOT EXECUTED. Existing online file remains SkyCompanion until quota recovers.
// Run only through use_figma after loading figma-use + figma-generate-library.
// File nbbKLI3KZ3GeQlUDFx24tT; inspect existing IDs first.
// Run one call for Components (3:54), then another for Foundations (3:55).
// The main flow repair already migrates page 0:1. Keep one page context per call.
const PAGE_ID='3:54';
const page=await figma.getNodeByIdAsync(PAGE_ID);
await figma.setCurrentPageAsync(page);
await Promise.all(['Regular','Semi Bold','Bold'].map(style=>figma.loadFontAsync({family:'Inter',style})));
const changed=[];
for(const node of page.query('*')){
  if(/\bSkyCompanion\b/.test(node.name)){node.name=node.name.replace(/\bSkyCompanion\b/g,'SkyCompanion');changed.push(node.id);}
  if(node.type==='TEXT'){
    const weight=node.fontName.style;
    node.fontName={family:'Inter',style:weight==='Semibold'?'Semi Bold':weight};
    node.characters=node.characters.replace(/\bSkyCompanion\b/g,'SkyCompanion');
    changed.push(node.id);
  }
  if(node.type==='COMPONENT'||node.type==='COMPONENT_SET')node.description=node.description.replace(/\bSkyCompanion\b/g,'SkyCompanion');
}
return {page:page.id,changed,remainingOldText:page.findAllWithCriteria({types:['TEXT']}).filter(n=>/\bSkyCompanion\b/.test(n.characters)).map(n=>n.id),previewFont:'Inter',nativeFont:'SwiftUI system'};
