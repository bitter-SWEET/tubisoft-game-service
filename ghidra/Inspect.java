import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
import java.util.*;

// Arguments: refs|function|callers ADDRESS...  or  range START END.
public class Inspect extends GhidraScript {
  private DecompInterface decompiler;
  private Set<Address> printed = new HashSet<>();
  private void show(Function f) {
    if (f == null || !printed.add(f.getEntryPoint())) return;
    println("FUNCTION " + f.getEntryPoint() + " " + f.getName() + " BODY " + f.getBody());
    DecompileResults result = decompiler.decompileFunction(f, 50, monitor);
    if (result.decompileCompleted()) println(result.getDecompiledFunction().getC());
    else println("DECOMPILE FAILED " + result.getErrorMessage());
  }
  public void run() throws Exception {
    String[] args = getScriptArgs();
    if (args.length < 2) throw new IllegalArgumentException("expected mode and addresses");
    decompiler = new DecompInterface(); decompiler.openProgram(currentProgram);
    if (args[0].equals("range")) {
      Address start = toAddr(args[1]), end = toAddr(args[2]);
      FunctionIterator it = currentProgram.getFunctionManager().getFunctions(start, true);
      while (it.hasNext()) { Function f = it.next(); if (f.getEntryPoint().compareTo(end)>0) break; println("ENTRY " + f.getEntryPoint() + " " + f.getName() + " " + f.getBody()); }
    } else for (int i=1;i<args.length;i++) {
      Address addr=toAddr(args[i]); println("TARGET " + addr);
      if (args[0].equals("function")) show(getFunctionContaining(addr));
      else if (args[0].equals("refs") || args[0].equals("callers")) {
        ReferenceIterator it=currentProgram.getReferenceManager().getReferencesTo(addr);
        while (it.hasNext()) { Reference ref=it.next(); Function f=getFunctionContaining(ref.getFromAddress()); println("REFERENCE " + ref.getFromAddress() + " " + ref.getReferenceType() + " FUNCTION " + f); if (args[0].equals("callers")) show(f); }
      } else throw new IllegalArgumentException("unknown mode");
    }
    decompiler.dispose();
  }
}
