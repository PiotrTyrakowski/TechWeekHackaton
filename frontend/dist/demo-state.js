// Add newly shipped demo deliveries while retaining saved user messages and replay.
export function mergeDemoRows(saved,incoming){
 const remaining=new Map();for(const row of saved)remaining.set(row.source_id,(remaining.get(row.source_id)||0)+1);
 const added=[];for(const row of incoming){const count=remaining.get(row.source_id)||0;if(count)remaining.set(row.source_id,count-1);else added.push(row);}
 return [...saved,...added];
}
