import math
import os
import traceback

FILE_NAME = "vdisk.dat"
vdisk = ...  # 虚拟磁盘文件

DISK_BLOCK = 128  # 块数
BLOCK_SIZE = 64  # 块大小
DISK_SIZE = DISK_BLOCK * BLOCK_SIZE
FAT_SIZE = math.ceil(DISK_BLOCK / BLOCK_SIZE)  # FAT表占用块数，也是根目录的FAT下标

FREE_FLAG = 0  # 空闲标志
END_FLAG = 255  # 结束标志
NOT_FOUND_FLAG = 254  # 没有该文件或目录

# EOF = bytes('#', 'ascii')[0]  # 文件尾空标志
# IDLE_ENTRY = bytes('$', 'ascii')[0]  # 目录项空标志
EOF = '#'
IDLE_ENTRY = '$'

FAT = []  # FAT表
dir_stack = []  # 目录栈 每一项是[目录项, 块号]
current_dir_files = []  # 当前目录文件列表 每一项是一个文件或目录的相关信息[文件名，文件类型，文件属性，文件起始块，文件长度]
open_files = []  # 所有打开文件的目录栈 每一项是一个[[目录项, 块号], ...]


ATTRIBUTE_DIR = 0b00001000
ATTRIBUTE_FILE = 0b00000100
ATTRIBUTE_SYS = 0b00000010
ATTRIBUTE_READONLY = 0b00000001


# 创建虚拟磁盘
def vdisk_create():
    f = open(FILE_NAME, 'wb+')
    diskdata = [0 for i in range(DISK_SIZE)]
    for i in range(FAT_SIZE):
        diskdata[i] = END_FLAG
    f.write(bytes(diskdata))
    f.close()


# 读取FAT表
def fat_read():
    global vdisk, FAT
    vdisk.seek(0)
    fat = vdisk.read(FAT_SIZE * BLOCK_SIZE)
    FAT = [i for i in fat]


# 显示FAT表
def fat_show(*args):
    '''显示FAT表'''
    global FAT
    for i, c in enumerate(FAT):
        # 一行显示16个字节
        if i % 16 == 0 and i != 0:
            print()
        print('{:02x}'.format(c), end=' ')
    print()


# 写入FAT表
def fat_write():
    global vdisk, FAT
    vdisk.seek(0)
    vdisk.write(bytes(FAT))


# 剩余空闲块数量
def vdisk_freeblocks():
    global FAT
    return FAT.count(FREE_FLAG)


# 关闭虚拟磁盘
def vdisk_close():
    global vdisk
    fat_write()
    vdisk.close()


# 读取一个块
def vdisk_readblock(block_num):
    global vdisk
    vdisk.seek(block_num * BLOCK_SIZE)
    data = vdisk.read(BLOCK_SIZE)
    return data


# 写入一个块
def vdisk_writeblock(block_num, data):
    global vdisk
    vdisk.seek(block_num * BLOCK_SIZE)
    vdisk.write(data)


# 得到下一个块的块号，参数是当前块号，返回下一个块号，如果没有下一个块，返回END_FLAG
def vdisk_nextblock(block_num):
    global FAT
    v = FAT[block_num]
    if FAT_SIZE < v < DISK_BLOCK:
        return v
    return END_FLAG


# 得到块号列表
# in vdisk_nextblock
#     v = FAT[block_num]
# TypeError: list indices must be integers or slices, not NoneType
def vdisk_getblocklist(block_num):
    block_numlist = []
    while block_num != END_FLAG:
        block_numlist.append(block_num)
        block_num = vdisk_nextblock(block_num)
    return block_numlist


# 读取一系列块
def vdisk_readblocks(block_num):
    block_numlist = vdisk_getblocklist(block_num)
    data = b''
    for i in block_numlist:
        data += vdisk_readblock(i)
    return data


# 写入一系列块
def vdisk_writeblocks(block_numlist, data):
    if len(data) // BLOCK_SIZE > len(block_numlist):
        data = data[:len(block_numlist) * BLOCK_SIZE]
    for i in range(len(data) // BLOCK_SIZE):
        vdisk_writeblock(
            block_numlist[i], data[i * BLOCK_SIZE: (i + 1) * BLOCK_SIZE])
    if len(data) % BLOCK_SIZE != 0:
        vdisk_writeblock(block_numlist[-1], data[-len(data) % BLOCK_SIZE:])


# 解码目录项
def get_fileinfo(item):
    filename = item[0:3].decode('ascii')
    for i in range(3):
        if item[i] == 0:
            filename = item[0:i].decode('ascii')
            break
    if len(filename) == 0 or filename == IDLE_ENTRY:
        return []
    filetype = item[3:5].decode('ascii')
    for i in range(3, 5):
        if item[i] == 0:
            filetype = item[3:i].decode('ascii')
            break
    fileattribute = item[5:6][0]
    filestart = item[6:7][0]
    filelength = item[7:8][0]
    return [filename, filetype, fileattribute, filestart, filelength]


# 编码目录项
def set_fileinfo(filename, filetype, fileattribute, filestart, filelength):
    fileinfo = []
    for i in range(3):
        if i < len(filename):
            fileinfo.append(ord(filename[i]))
        else:
            fileinfo.append(0)
    for i in range(2):
        if i < len(filetype):
            fileinfo.append(ord(filetype[i]))
        else:
            fileinfo.append(0)
    fileinfo.append(fileattribute)
    fileinfo.append(filestart)
    fileinfo.append(filelength)
    return bytes(fileinfo)


# 读取目录项，参数是目录项起始块号
def vdisk_listread(block_num):
    blocks = vdisk_readblocks(block_num)
    dir_files = []
    for i in range(len(blocks)//8):
        fileinfo = get_fileinfo(blocks[i*8:i*8+8])
        if len(fileinfo) > 0:
            dir_files.append(fileinfo)
    return dir_files


# 申请n个块的空间，返回空闲块号列表
def vdisk_alloc(n, start=-1):
    # if n <= 0:
    #     return []
    global FAT
    block_numlist = []
    if start != -1:
        block_numlist.append(start)
        FAT[start] = END_FLAG
        n -= 1
        if n == 0:
            return block_numlist
    for i, c in enumerate(FAT):
        if c == FREE_FLAG:
            block_numlist.append(i)
            n -= 1
            if n == 0:
                break
    if n > 0:
        return []
    for i in range(len(block_numlist) - 1):
        FAT[block_numlist[i]] = block_numlist[i + 1]
    FAT[block_numlist[-1]] = END_FLAG
    return block_numlist


# 释放空间，参数是空闲块号列表或第一个空闲块号
def vdisk_free(block_num):
    global FAT
    if isinstance(block_num, int):
        block_num = vdisk_getblocklist(block_num)
    for i in range(len(block_num)):
        FAT[block_num[i]] = FREE_FLAG


# 写入目录项，参数是目录项起始块号，参数是目录项列表
def vdisk_listwrite(block_num, dir_files):
    vdisk_free(block_num)
    block_numlist = vdisk_alloc(math.ceil(len(dir_files)/8), block_num)
    lists = b''
    for i in range(len(dir_files)):
        lists += set_fileinfo(*dir_files[i])
    if len(dir_files) % 8 != 0:
        lists += set_fileinfo(IDLE_ENTRY, '',
                              ATTRIBUTE_DIR, END_FLAG, END_FLAG)
    vdisk_writeblocks(block_numlist, lists)


# 虚拟磁盘初始化、加载
def vdisk_init():
    global vdisk, dir_stack, current_dir_files
    if not os.path.exists(FILE_NAME) or os.path.getsize(FILE_NAME) == 0:
        vdisk_create()
    vdisk = open(FILE_NAME, 'rb+')
    fat_read()
    dir_stack = [['', FAT_SIZE]]
    current_dir_files = vdisk_listread(FAT_SIZE)


# 格式化虚拟磁盘
def format_disk(*args):
    '''格式化虚拟磁盘'''
    global vdisk
    print("格式化磁盘将会清除原有数据，是否继续？(y/n)")
    if input().upper() != 'Y':
        return
    vdisk.close()
    vdisk_init()


# in vdisk_gwd
#     return '/'.join(ds)
# TypeError: sequence item 0: expected str instance, list found
def vdisk_gwd(*args):
    global dir_stack
    ds = args[0] if len(args) > 0 else [d[0] for d in dir_stack]
    if len(ds) > 1:
        return '/'.join(ds)
    return '/'


def get_attributes_string(fileattribute):
    s = '----'
    s += 'd' if fileattribute & ATTRIBUTE_DIR else '-'
    s += 'f' if fileattribute & ATTRIBUTE_FILE else '-'
    s += 's' if fileattribute & ATTRIBUTE_SYS else '-'
    s += 'r' if fileattribute & ATTRIBUTE_READONLY else '-'
    return s


def show_diritems(dir_files):
    for filename, filetype, fileattribute, filestart, filelength in dir_files:
        print('{:4s}\t{:3s}\t{:9s}\t{:4d}\t{:d}'.format(
            filename, filetype, get_attributes_string(fileattribute), filestart, filelength))


# 路径解析，返回该目录的绝对路径栈
# bug:创建文件后当前路径改变
# /]>>>md a
# 目录创建成功
# /a]>>>
def path_decode(spath):
    global dir_stack, current_dir_files
    mypath = []
    temp_dir_files = []
    if not spath.startswith('/'):
        mypath = dir_stack[:]
        temp_dir_files = current_dir_files[:]
    for p in spath.split('/'):
        if p == '..':
            if len(mypath) > 1:
                mypath.pop()
        elif p != '':
            flat = False
            for filename, filetype, fileattribute, filestart, filelength in temp_dir_files:
                if filename == p:
                    mypath.append([p, filestart])
                    temp_dir_files = vdisk_listread(filestart)
                    flat = True
                    break
            if not flat:
                mypath.append([p, NOT_FOUND_FLAG])
        else:
            mypath = [['', FAT_SIZE]]
    # 单层路径超过三个字符，截取前三个字符
    for i in range(len(mypath)):
        if len(mypath[i][0]) > 3:
            mypath[i][0] = mypath[i][0][:3]
    return mypath


# 判断路径是否存在
def path_exist(path_stack):
    if len(path_stack) == 1:
        return True
    for p, b in path_stack:
        if b == NOT_FOUND_FLAG:
            return False
    return True


# 判断路径是否是目录，只有当前路径存在时有意义
def path_isdir(path_stack):
    if len(path_stack) == 1:
        return True
    # path_stack[-1]


def path_isfile(path_stack):
    if len(path_stack) == 1:
        return False
    # path_stack[-1]


# 判断path1是否是path2的父路径
def is_father(path1, path2):
    if len(path1) > len(path2):
        return False
    for i in range(len(path1)):
        if path1[i][0] != path2[i][0]:
            return False
    return True


# 显示已经打开的文件
def show_open_files():
    global open_files
    for f in open_files:
        print(vdisk_gwd(f[0]))


# 递归创建目录
def create_dir(path_stack):
    if len(path_stack) == 1:
        return path_stack[-1][1]
    if not path_exist(path_stack[:-1]):
        create_dir(path_stack[:-1])
    dir_files = vdisk_listread(path_stack[-2][1])
    for filename, filetype, fileattribute, filestart, filelength in dir_files:
        if filename == path_stack[-1][0]:
            print('目录已存在')
            return
    dir_files.append(
        [path_stack[-1][0], 'd', ATTRIBUTE_FILE, END_FLAG, END_FLAG])
    vdisk_listwrite(path_stack[-2][1], dir_files)
    print('目录创建成功')


# 创建文件（create_file）、打开文件(open_file)、关闭文件(close_file)、读文件(read_file)、
# 写文件（write_file）、删除文件(delete_file)、显示文件内容(typefile) 、改变文件属性(change)、
# 创建目录(md)、列表目录(dir)、删除空目录(rd)、查看FAT表(fat_show)、格式化虚拟磁盘(format_disk)
def create_file(*args):
    # global current_dir_files
    '''创建文件:create_file filename'''
    if len(args) != 1:
        print(create_file.__doc__)
        return
    path_stack = path_decode(args[0])
    if path_exist(path_stack):
        print("文件或路径已存在")
        return
    if not path_exist(path_stack[:-1]):
        b = create_dir(path_stack[:-1])
    else:
        b = path_stack[-2][1]
    # 创建文件
    dir_files = vdisk_listread(b)
    dir_files.append([path_stack[-1][0], 'f', ATTRIBUTE_FILE, END_FLAG, 0])
    vdisk_listwrite(b, dir_files)
    print('文件创建成功')


def open_file(*args):
    '''打开文件:open_file filename'''
    if len(args) != 1:
        print(open_file.__doc__)
        return
    path_stack = path_decode(args[0])
    if not path_exist(path_stack):
        print("文件不存在")
        return
    global open_files
    if path_isfile():
        open_files.append(path_stack)
        print("打开已打开")


def close_file(*args):
    '''关闭文件:close_file filename'''
    if len(args) != 1:
        print(close_file.__doc__)
        return
    path_stack = path_decode(args[0])
    global open_files
    for f in open_files:
        if is_father(f, path_stack):
            open_files.remove(f)
            print("文件已关闭")
            return
    print("文件未打开")


# bytes转换为str
def get_filecontent(context):
    s = ''
    for i in context:
        s += chr(i)
    return s


def read_file(*args):
    '''读文件:read_file filename'''
    if len(args) != 1:
        print(read_file.__doc__)
        return
    path_stack = path_decode(args[0])
    if not path_exist(path_stack):
        print("文件不存在")
        return
    if not path_isfile(path_stack):
        print("不是文件")
        return
    dir_files = vdisk_listread(path_stack[-2][1])
    for filename, filetype, fileattribute, filestart, filelength in dir_files:
        if filename == path_stack[-1][0]:
            context = vdisk_readblocks(filestart)[:filelength]
            break
    content = get_filecontent(context)
    print(content)


def write_file(*args):
    '''写文件:write_file filename data'''
    if len(args) < 1:
        print(write_file.__doc__)
        return
    path_stack = path_decode(args[0])
    if not path_exist(path_stack):
        print("文件不存在")
        return
    if not path_isfile(path_stack):
        print("不是文件")
        return
    dir_files = vdisk_listread(path_stack[-2][1])
    for i in range(len(dir_files)):
        if dir_files[i][0] == path_stack[-1][0]:
            filename, filetype, fileattribute, filestart, filelength = dir_files[i]
            context = vdisk_readblocks(filestart)[:filelength]
            break
    content = get_filecontent(context)
    if len(args) == 1:
        content += input(content)
    else:
        content += ' '.join(args[1:])
    context = bytes(content, encoding='ascii')
    filelength = len(context)
    dir_files[i] = [filename, filetype, fileattribute, filestart, filelength]
    # 更新属性
    vdisk_listwrite(path_stack[-2][1], dir_files)
    # 更新文件
    vdisk_free(filestart)
    block_numlist = vdisk_alloc(math.ceil(filelength / BLOCK_SIZE), 'f')
    vdisk_writeblocks(block_numlist, context)


def delete_file(*args):
    '''删除文件:delete_file filename'''
    if len(args) != 1:
        print(delete_file.__doc__)
        return
    path_stack = path_decode(args[0])
    global open_files
    for f in open_files:
        if is_father(f, path_stack):
            print("文件已打开，请关闭后再删除")
            return
    if not path_exist(path_stack):
        print("文件不存在")
        return
    if not path_isfile(path_stack):
        print("不是文件")
        return
    dir_files = vdisk_listread(path_stack[-2][1])
    for i in range(len(dir_files)):
        if dir_files[i][0] == path_stack[-1][0]:
            dir_files.pop(i)
            break
    vdisk_listwrite(path_stack[-2][1], dir_files)


def typefile(*args):
    '''显示文件内容:typefile filename'''
    read_file(*args)


def change(*args):
    '''改变文件属性:change filename [s|r]'''
    if len(args) != 2:
        print(change.__doc__)
        return
    path_stack = path_decode(args[0])
    if not path_exist(path_stack):
        print("文件不存在")
        return
    if not path_isfile(path_stack):
        print("不能改变非文件属性")
        return
    dir_files = vdisk_listread(path_stack[-2][1])
    for i in range(len(dir_files)):
        if dir_files[i][0] == path_stack[-1][0]:
            if 's' in args[1]:
                dir_files[i][2] |= ATTRIBUTE_SYS
            elif 'r' in args[1]:
                dir_files[i][2] |= ATTRIBUTE_READONLY
            else:
                print("参数错误")
                return
            break
    vdisk_listwrite(path_stack[-2][1], dir_files)


def md(*args):
    '''创建目录:md <path>'''
    if len(args) != 1:
        print(md.__doc__)
        return
    path_stack = path_decode(args[0])
    if path_exist(path_stack):
        print("文件或路径已存在")
        return
    create_dir(path_stack)


def dir(*args):
    '''列表目录:dir [path] 缺省为当前目录'''
    if len(args) > 1:
        print(dir.__doc__)
        return
    if len(args) == 0:
        show_diritems(current_dir_files)
    else:
        mypath = path_decode(args[0])
        if not path_exist(mypath):
            print("目录不存在")
            return
        dir_files = vdisk_listread(mypath[-1][1])
        show_diritems(dir_files)


def path_isempty(path_stack):
    if path_stack[-1][1] == END_FLAG:
        return True


def rd(*args):
    '''删除空目录:rd <path>'''
    if len(args) != 1:
        print(rd.__doc__)
        return
    path_stack = path_decode(args[0])
    if len(path_stack) <= 1:
        print("不能删除根目录")
        return
    if not path_exist(path_stack):
        print("目录不存在")
        return
    if not path_isdir(path_stack):
        print("不是目录")
        return
    if not path_isempty(path_stack):
        print("目录不为空")
        return
    global dir_stack
    if is_father(path_stack, dir_stack):
        print("删除的目录是当前目录的父目录，请先退出当前目录")
        return
    dir_files = vdisk_listread(path_stack[-2][1])
    for i in range(len(dir_files)):
        if dir_files[i][0] == path_stack[-1][0]:
            dir_files.pop(i)
            break
    vdisk_listwrite(path_stack[-2][1], dir_files)


# in q
#     exit(0)
# SystemExit: 0
def q(*args):
    '''退出程序'''
    vdisk_close()
    print('Bye!')
    os._exit(0)


operator_dict = {'create_file': create_file, 'open_file': open_file, 'close_file': close_file,
                 'read_file': read_file, 'write_file': write_file, 'delete_file': delete_file,
                 'typefile': typefile, 'change': change, 'md': md, 'dir': dir, 'rd': rd,
                 'fat_show': fat_show, 'format_disk': format_disk, 'q': q}


def h():
    for k, v in operator_dict.items():
        print('{:15s}'.format(k) + str(v.__doc__))


def not_found(*args):
    print('命令未找到，请检查输入或键入h查看帮助')


# 程序开始
# bug:current_dir_files不更新
# /]>>>create_file a
# 文件创建成功
# /]>>>dir
# /]>>>
vdisk_init()
print('==============================虚拟磁盘文件管理==============================')
print('键入h查看帮助')
while True:
    try:
        cmds = input(vdisk_gwd() + ']>>>')
        if cmds == '':
            continue
        if cmds == 'h':
            h()
            continue
        cmds = cmds.split()
        operator_dict.get(cmds[0], not_found)(*cmds[1:])
        current_dir_files = vdisk_listread(FAT_SIZE)
    except:
        print('出现异常, 程序即将退出')
        traceback.print_exc()
        break
q()
