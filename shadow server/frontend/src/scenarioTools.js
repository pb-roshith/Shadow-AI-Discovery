const statusPriority={Approved:0,Unknown:1,Restricted:2,Revoked:3};

export function scenarioToolApprovals(candidates) {
 const tools=new Map();
 for(const candidate of candidates){
  const inventory=candidate.inventory||{};
  const provider=inventory.provider||candidate.provider;
  const name=inventory.tool_name||provider;
  const status=inventory.tool_status??inventory.status??'Unknown';
  const key=JSON.stringify([provider.toLowerCase(),name.toLowerCase()]);
  const previous=tools.get(key);
  // Multiple usage sessions share one global approval. Retain the stricter
  // status if records disagree, and link to a candidate with that status.
  if(!previous||(statusPriority[status]??1)>(statusPriority[previous.status]??1)){
   tools.set(key,{key,provider,name,status,candidate});
  }
 }
 return [...tools.values()];
}
