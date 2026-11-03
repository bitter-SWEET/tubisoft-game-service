import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;

public class FindBootstrap extends GhidraScript {
 public void run() throws Exception {
  DecompInterface d = new DecompInterface(); d.openProgram(currentProgram);
  long[] offsets = {0x2c2c10L,0x2e7f88L,0x2e7f98L,0x2e7fa0L,0x2e7fd0L,0x2e7fe0L,0x2e7ff0L,0x2e8090L,0x2ddb70L};
  for (long off : offsets) {
   Address a = toAddr(0x100000L + off - 0x100L);
   println("=== FILE " + Long.toHexString(off) + " ADDRESS " + a + " ===");
   ReferenceIterator refs = currentProgram.getReferenceManager().getReferencesTo(a);
   while (refs.hasNext()) {
    Reference ref=refs.next(); Function f=getFunctionContaining(ref.getFromAddress());
    println("REF " + ref.getFromAddress() + " FUNCTION " + (f == null ? "none" : f.getEntryPoint()));
    if (f != null) { DecompileResults res=d.decompileFunction(f, 45, monitor); if(res.decompileCompleted()) println(res.getDecompiledFunction().getC()); }
   }
  }
  d.dispose();
 }
}
