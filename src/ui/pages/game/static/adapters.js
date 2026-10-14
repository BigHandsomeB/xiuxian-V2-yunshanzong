// Read-only UI adapters. Classification labels add no Domain fields or gameplay.
export function categoryFor(id,row){if(row.category)return row.category;if(id==='herb'||/草|药材/.test(row.name||''))return 'herb';if(id==='pill'||id.includes('pill')||/丹$/.test(row.name||''))return 'pill';return 'resource';}
export function gameView(response){const v=response.view,inventory={};for(const [id,row]of Object.entries({...v.inventory,...v.holdings})){inventory[id]={...row,category:categoryFor(id,row)};}
 const groups=v.disciples?.groups||[];
 return {...response,view:{...v,inventory,disciples:{...v.disciples,groups},work:{...v.work,total_count:groups.reduce((sum,g)=>sum+g.count,0)}}};}
export const alchemyAdapter={start:ctx=>ctx.action('start'),assign:ctx=>ctx.action('assign'),unassign:ctx=>ctx.action('unassign')};
