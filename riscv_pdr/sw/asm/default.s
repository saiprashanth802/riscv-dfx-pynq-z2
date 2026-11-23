addi x1,x0,6
addi x2,x0,7
add  x3,x1,x2        # 13
sub  x4,x2,x1        # 1
sw   x3,0(x0)        # mem[0]=13
sw   x4,4(x0)        # mem[1]=1
lui  x5,0xF0000      # CFU base
sw   x1,0(x5)        # op_a=6
sw   x2,4(x5)        # op_b=7
addi x8,x0,0
sw   x8,8(x5)        # fn=0
lw   x9,12(x5)       # read result
sw   x9,16(x0)       # mem[4]
addi x8,x0,1
sw   x8,8(x5)        # fn=1
lw   x9,12(x5)       # read result
sw   x9,20(x0)       # mem[5]
addi x8,x0,2
sw   x8,8(x5)        # fn=2
lw   x9,12(x5)       # read result
sw   x9,24(x0)       # mem[6]
addi x8,x0,3
sw   x8,8(x5)        # fn=3
lw   x9,12(x5)       # read result
sw   x9,28(x0)       # mem[7]
lui  x7,0x10         # 0x00010000
sw   x7,0(x5)        # op_a
sw   x7,4(x5)        # op_b
addi x8,x0,0
sw   x8,8(x5)        # fn=0
lw   x9,12(x5)       # read result
sw   x9,32(x0)       # mem[8]
addi x8,x0,1
sw   x8,8(x5)        # fn=1
lw   x9,12(x5)       # read result
sw   x9,36(x0)       # mem[9]
addi x8,x0,2
sw   x8,8(x5)        # fn=2
lw   x9,12(x5)       # read result
sw   x9,40(x0)       # mem[10]
jal  x0,0            # halt
