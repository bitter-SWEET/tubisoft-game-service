import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.listing.*;
public class OverlayDetail extends GhidraScript {
 public void run() throws Exception {
  DecompInterface d=new DecompInterface(); d.openProgram(currentProgram);
  for(long a : new long[]{0x1d5ba00L,0x1d5bbe0L,0x1d59410L,0x1d59500L,0x1d59920L,0x1d83bb0L}) {
   Function f=getFunctionAt(toAddr(a)); println("FUNCTION " + f); if(f!=null) { DecompileResults r=d.decompileFunction(f,45,monitor); if(r.decompileCompleted()) println(r.getDecompiledFunction().getC()); }
  } d.dispose();
 }
}
