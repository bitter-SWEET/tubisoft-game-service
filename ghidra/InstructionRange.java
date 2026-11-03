import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Instruction;

// Print disassembly for inclusive addresses; undefined code is disassembled first.
public class InstructionRange extends GhidraScript {
 public void run() throws Exception {
  String[] args=getScriptArgs(); if(args.length!=2) throw new IllegalArgumentException("start end");
  Address a=toAddr(args[0]), end=toAddr(args[1]);
  while(a.compareTo(end)<=0) {
   Instruction ins=getInstructionAt(a);
   if(ins==null) { disassemble(a); ins=getInstructionAt(a); }
   if(ins==null) { println(a + " <undefined>"); a=a.add(4); }
   else { println(a + " " + ins); a=a.add(ins.getLength()); }
  }
 }
}
