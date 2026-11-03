import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
public class OverlayRefs extends GhidraScript {
 public void run() throws Exception {
  DecompInterface d = new DecompInterface(); d.openProgram(currentProgram);
  for(long off : new long[]{0xa6840L,0xa6860L,0xa75f0L,0xa7610L,0xa8530L}) {
   println("OFFSET " + Long.toHexString(off)); ReferenceIterator it=currentProgram.getReferenceManager().getReferencesTo(toAddr(0x1cee500L+off));
   while(it.hasNext()) {Reference r=it.next(); Function f=getFunctionContaining(r.getFromAddress()); println("REF " + r.getFromAddress() + " FUNCTION " + f); if(f!=null){DecompileResults res=d.decompileFunction(f,45,monitor); if(res.decompileCompleted()) println(res.getDecompiledFunction().getC());}}
  }
  d.dispose();
 }
}
