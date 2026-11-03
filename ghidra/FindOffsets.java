import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.*;

// Locate candidate accesses to object-field offsets within a code range.
public class FindOffsets extends GhidraScript {
  public void run() throws Exception {
    String[] args = getScriptArgs();
    if (args.length < 3) throw new IllegalArgumentException("start end offset...");
    Address end = toAddr(args[1]);
    InstructionIterator it = currentProgram.getListing().getInstructions(toAddr(args[0]), true);
    while (it.hasNext()) {
      Instruction ins = it.next();
      if (ins.getAddress().compareTo(end) > 0) break;
      String rendered = ins.toString();
      for (int i = 2; i < args.length; i++) {
        if (rendered.contains(args[i] + "(")) {
          Function fn = getFunctionContaining(ins.getAddress());
          println(ins.getAddress() + " " + rendered + " FUNCTION " + fn);
        }
      }
    }
  }
}
