#!/usr/bin/python

import argparse
import simplepdb as pdb
import pdb_util as util
import os, shutil, glob, sys
from plumbum import FG
from plumbum.cmd import sed, grep, cut, uniq, wc
try:
    from plumbum.cmd import obabel
except ImportError:
    raise ImportError('Check that obabel is on your path')
try:
    from plumbum.cmd import antechamber, parmchk, pdb4amber, tleap, pmemd_cuda
except ImportError:
    raise ImportError('Check that AMBER binaries are on your path')

def get_cmd(input_str):
    cmd_dict = {'.frcmod' : 'loadamberparams', '.lib' : 'loadoff', '.off' : 
            'loadoff', '.prep' : 'loadAmberPrep', '.mol2' : 'loadmol2', '.pdb' :
            'loadpdb'}
    ext = os.path.splitext(input_str)[-1]
    return cmd_dict[ext]


def make_amber_parm(fname, base, ff, molname='', water_model = '', 
        wat_dist = 0, libs=[], frcmod = ''):
    '''
    Generate AMBER parameters with tleap
    '''
    inpcrd = base + '.inpcrd'
    prmtop = base + '.prmtop'
    if not molname: molname = fname[:3].upper()

    with open(base + '.tleap', 'w') as leap_input:
        leap_input.write('source ' + ff + '\n' + 
                'source leaprc.gaff\n')
        for lib in libs:
            leap_input.write(get_cmd(lib) + ' ' + lib + '\n')
        leap_input.write(molname + '=' + get_cmd(fname) + ' ' + fname + '\n')
        if water_model:
            leap_input.write('source ' + water_model + '\n' + 
                    'solvateoct '+molname+' TIP3PBOX ' + str(wat_dist) + '\n' + 
                    'addions '+molname+' Na+ 0\n' + 
                    'addions '+molname+' Cl- 0\n')
        elif frcmod:
            leap_input.write('loadamberparams '+frcmod+'\n' + 
                    'saveoff '+molname+' '+base+'.lib\n')
        leap_input.write('saveamberparm ' + molname+ ' ' + prmtop + ' ' + inpcrd + '\n')
        leap_input.write('quit\n')
    tleap['-f', base + '.tleap'] & FG

def do_amber_min_constraint(fname, base):
    '''
    Do AMBER minimization with protein constraint
    '''
    try:
        numres = (grep['ATOM', fname] | cut['-b', '23-26'] | uniq | wc)()
        numres = numres.split()[0].strip()
    except Exception as e:
        if e[1] == 1:
            numres = 0
    with open(base + '_min1.in', 'w') as min_input:
        min_input.write(base + ': initial minimization solvent + ions\n' + 
            ' &cntrl\n' + 
            '  imin   = 1,\n' + 
            '  maxcyc = 1000,\n' +
            '  ncyc   = 500,\n' +
            '  ntb    = 1,\n' +
            '  ntr    = 1,\n' +
            '  cut    = 10.0\n' +
            ' /\n' +
            'Hold the protein fixed\n' +
            '500.0\n' +
            'FIND\n' +
            '* * S *\n' +
            '* * B *\n' +
            '* * 3 *\n' +
            '* * E *\n' +
            '* * M *\n' +
            'SEARCH\n' +
            'RES 1 ' + str(numres) + '\n' +
            'END\n' +
            'END\n')
    command = pmemd_cuda['-O', '-i', base+'_min1.in', '-o', base+'_min1.out', '-p',
            base+'.prmtop', '-c', base+'.inpcrd', '-r', base+'_min1.rst',
            '-ref', base+'.inpcrd'] 
    print command
    command & FG

def do_amber_min(base):
    '''
    Do unconstrained AMBER minimization 
    '''
    with open(base + '_min2.in', 'w') as min_input:
        min_input.write(base + ':  minimization whole system\n' + 
            ' &cntrl\n' + 
            '  imin   = 1,\n' + 
            '  maxcyc = 5000,\n' + 
            '  ncyc   = 2000,\n' + 
            '  ntb    = 1,\n' + 
            '  ntr    = 0,\n' + 
            '  cut    = 10.0\n' + 
            ' /\n')
    command = pmemd_cuda['-O', '-i', base+'_min2.in', '-o', base+'_min2.out', '-p',
            base+'.prmtop', '-c', base+'_min1.rst', '-r', base+'_min2.rst'] 
    print command
    command & FG

def do_amber_warmup(fname, base, temperature):
    '''
    Do AMBER MD to gradually increase system to target temp
    '''
    try:
        numres = (grep['ATOM', fname] | cut['-b', '23-26'] | uniq | wc)()
        numres = numres.split()[0].strip()
    except Exception as e:
        if e[1] == 1:
            numres = 0
    with open(base + '_md1.in','w') as md_input:
        md_input.write(' &cntrl\n' + 
              '  imin   = 0,\n' + 
              '  irest  = 0,\n' + 
              '  ntx    = 1,\n' + 
              '  ntb    = 1,\n' + 
              '  cut    = 10.0,\n' + 
              '  ntr    = 1,\n' + 
              '  ntc    = 2,\n' + 
              '  ntf    = 2,\n' + 
              '  tempi  = 0.0,\n' + 
              '  temp0  = ' + str(temperature) + '\n' + 
              '  ntt    = 3,\n' + 
              '  gamma_ln = 1.0,\n' + 
              '  nstlim = 50000, dt = 0.002, ntxo = 2,\n' + 
              '  ntpr = 1000, ntwx = 1000, ntwr = 10000,\n' + 
              '  ioutfm = 1\n' + 
              ' /\n' + 
            'Keep prot fixed with weak restraints\n' + 
            '10.0\n' + 
            'FIND\n' + 
            '* * S *\n' + 
            '* * B *\n' + 
            '* * 3 *\n'  
            '* * E *\n' + 
            '* * M *\n' + 
            'SEARCH\n' + 
            'RES 1 ' + str(numres) + '\n' + 
            'END\n' + 
            'END\n')
    command = pmemd_cuda['-O', '-i', base+'_md1.in', '-o', base+'_md1.out', '-p',
            base+'.prmtop', '-c', base+'_min2.rst', '-r', base+'_md1.rst',
            '-ref', base+'_min2.rst', '-x', base+'_md1.nc'] 
    print command
    command & FG

def do_amber_constant_pressure(base, temp):
    '''
    Do AMBER MD to equilibrate system at constant pressure
    '''
    with open(base + '_md2.in','w') as md_input:
        md_input.write(base + ': 100ps MD\n' + 
             ' &cntrl\n' + 
             '  imin = 0, irest = 1, ntx = 7,\n' + 
             '  ntb = 2, pres0 = 1.0, ntp = 1,\n' + 
             '  taup = 2.0,\n' + 
             '  cut = 10.0, ntr = 0,\n' + 
             '  ntc = 2, ntf = 2,\n' + 
             '  tempi = '+str(temp)+', temp0 = '+str(temp)+',\n' + 
             '  ntt = 3, gamma_ln = 1.0,\n' + 
             '  nstlim = 50000, dt = 0.002, ntxo = 2,\n' + 
             '  ntpr = 5000, ntwx = 5000, ntwr = 500000,\n' + 
             '  ioutfm = 1\n' + 
             ' /\n')
    command = pmemd_cuda['-O', '-i', base+'_md2.in', '-o', base+'_md2.out', '-p',
            base+'.prmtop', '-c', base+'_md1.rst', '-r', base+'_md2.rst',
            '-x', base+'_md2.nc'] 
    print command
    command & FG

def make_amber_production_input(base, length, keep_velocities, coord_dump_freq):
    '''
    Make input files for production run AMBER MD; length is in nanoseconds
    '''
    nstlim = float(length) / .000002
    irest = int(keep_velocities)
    ntx = 7 if keep_velocities else 1
    with open(base + '_md3.in','w') as md_input:
        md_input.write(base + ': ' + str(length) + 'ns MD\n' + 
            ' &cntrl\n' + 
            '  imin = 0, irest = '+str(irest)+', ntx = '+str(ntx)+',\n' + 
            '  ntb = 2, pres0 = 1.0, ntp = 1,\n' + 
            '  taup = 2.0,\n' + 
            '  cut = 10.0, ntr = 0,\n' + 
            '  ntc = 2, ntf = 2,\n' + 
            '  tempi = $temp, temp0 = $temp,\n' + 
            '  ntt = 3, gamma_ln = 1.0,\n' + 
            '  nstlim = '+str(nstlim)+', dt = 0.002, ntxo = 2,\n' + 
            '  ntpr = 5000, ntwx = '+str(coord_dump_freq)+', ntwr = 500000,\n' + 
            '  ioutfm = 1\n' + 
             '/\n')

def do_amber_preproduction(fname, base, args, ff):
    '''
    Do minimization with constraints, minimization without constraints, initial
    MD as temperature is raised to target temp, second MD where system is
    equilibrated at constant pressure, and generate input files for production
    run MD but don't run it (becuz it's PREproduction, see?)
    '''
    do_amber_min_constraint(fname, base)
    do_amber_min(base)
    do_amber_warmup(fname, base, args.temperature)
    do_amber_constant_pressure(base, args.temperature)
    make_amber_production_input(base, args.prod_length, args.keep_velocities,
            args.coord_dump_freq)

def do_amber_production(base):
    '''
    Does AMBER production run MD locally
    '''
    command = pmemd_cuda['-O', '-i', base+'_md3.in', '-o', base+'_md3.out', '-p',
            base+'.prmtop', '-c', base+'_md2.rst', '-r', base+'_md3.rst',
            '-x', base+'_md3.nc'] 
    print command
    command & FG

def do_antechamber(fname, net_charge, ff, molname, base = ''):
    '''
    Run antechamber and get correctly named versions of the following: mol2
    with bcc charges, frcmod, lib, prmtop, inpcrd
    '''
    if not base: base = util.get_base(fname)
    ext = os.path.splitext(fname)[-1]
    ext = ext.lstrip('.')
    mol2 = base + '_amber.mol2'
    try:
        command = antechamber['-i', fname, '-fi', ext, '-o', mol2, '-fo', 'mol2', '-c',
                'bcc', '-nc', str(net_charge), '-s', '2']
        print command
        command & FG
    except Exception as e:
        print 'Antechamber failed. Check {0} structure. Aborting...\n'.format(fname)
        sys.exit()

    frcmod = base + '.frcmod'
    parmchk['-i', mol2, '-f', 'mol2', '-o', frcmod]()
    make_amber_parm(mol2, base, ff, molname=molname, frcmod=frcmod)

def set_matches(fname, libs, reslist, orphaned_res, mol, force=False):
    '''
    Find whether any units defined by a lib are required; if they are, update
    the liblist to include that lib and remove the units it defines from
    orphaned_res
    '''
    units = util.get_units(fname)
    matches = set(units).intersection(reslist)
    #TODO: make this work for prep and check bonds as well as atoms.
    #require that atom names and connectivity match before adding lib
    libatoms = []
    ext = os.path.splitext(fname)[-1][0:4]
    if ext != 'prep':
        with open(fname,'r') as f:
            atomcopy = False
            for line in f:
                if line.startswith('!'):
                    if line.split()[0].split('.')[-1] == 'atoms':
                        atomcopy = True
                    else:
                        atomcopy = False
                elif atomcopy:
                    libatoms.append(line.strip().strip('"'))
    if set(libatoms) != set(mol.mol_data['atomname']) or ext == 'prep' and not force:
        matches = set([])
    if matches:
        #redefine a unit iff found in a user-provided lib, but warn the user about the
        #duplication. don't redefine if found locally. 
        if not matches.intersection(orphaned_res) and not force:
            print 'Unit %s found in %s defined previously, \
            skipping to avoid redefinition\n' % (' '.join(match for match in
                matches), fname)
        else:
            if not matches.intersection(orphaned_res):
                print 'Unit %s found in %s defined previously, \
                adding user-provided lib but redefinition may cause problems\n' \
                % (' '.join(match for match in matches), fname)
            libs.add(fname)
            frcmod = util.get_base(fname) + '.frcmod'
            if os.path.isfile(frcmod):
                lib.add(frcmod)
            orphaned_res -= matches

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Generates pre-production files for AMBER \
    MD. Can handle a receptor or ligand by themselves (checks for ligand library \
    files in the current directory and generates them if they don't exist) or \
    sets up the complex if given both a receptor and ligand.")

    parser.add_argument('-s', '--structures', nargs='+', required=True, help='Structures \
    for which you want to run a simulation. N.B. if more than one is provided \
    they will be simulated together.')

    parser.add_argument('-n', '--out_name', default='complex',
    help='Optionally provide a filename for the created complex; only \
    used if you provide more than one structure. Default is "complex."')

    parser.add_argument('-p', '--libs', nargs='+', required=False, help="Optionally specify \
    a prefix for nonstandard residue library files; this can include their path if they aren't \
    in the current directory. If the relevant files exist we assume you want \
    to use them, otherwise we assume this is where you want them to go and \
    derive the residue name accordingly.")

    parser.add_argument('-w', '--water_dist', default=12, help='Water box \
    distance; defaults to 12.')

    parser.add_argument('-wm', '--water_model', default='leaprc.water.tip3p',
            help='Water model; OPC, SPCE, TIP4P, and TIP3P are available. \
            Defaults to TIP3P.')

    parser.add_argument('-ff', '--force_field', default='leaprc.protein.ff15ipq',
            help='Force field; defaults to ff15ipq.')

    parser.add_argument('-t', '--temperature', default=300, help='Simulation \
    temperature; defaults to 300K.')

    parser.add_argument('-l', '--prod_length', default=100, help='Length of \
    production-run MD. This is used to generate the input files for that MD, \
    but note that by default this MD is not run. Units are nanoseconds.')

    parser.add_argument('-k', '--keep_velocities', default=False,
            action='store_true', help='Keep velocities from preproduction run \
                    when starting the production MD. Default is false.')

    parser.add_argument('-r', '--run_prod_md', default=False,
    action='store_true', help='Run production MD locally when all preprocessing \
    is finished. Default is false, because you might want to run it on a \
    cluster.')

    parser.add_argument('-noh', '--no_touch_hyd', dest='noh', default=False,
            action='store_true', help="Don't remove any hydrogens.")

    parser.add_argument('-parm', '--parm_only', action='store_true', default =
    False, help="Only generate the necessary ligand parameters, don't do the \
    preproduction MDs")

    parser.add_argument('-ui', '--uninteractive', action='store_true',
            default=False, help="Turn off interactive mode, which exists to let \
            you check the output of pdb4amber for potentially serious problems \
            with input structures.")

    parser.add_argument('-O', '--overwrite', action='store_false',
            default=True, help='Overwrite files in the current directory that \
            are generated by this script. Default is True.')

    parser.add_argument('-df', '--coord_dump_freq', default=5000,
    help='Frequency for dumping coordinates to traj_file. Defaults to 5000. \
    The old script referred to this as the "timestep."')

    #TODO: add extra tleap arg passing
    #TODO: generate PBS file

    #TODO: deal with different water models including with waters already in
    #input
    args = parser.parse_args()

    #Check whether AMBERHOME is set and the desired force field is available
    amberhome = os.environ['AMBERHOME']
    if not amberhome:
        print "Warning: AMBERHOME is not set! This is likely to cause problems \
        later.\n"
    else:
        if not os.path.isfile(amberhome + '/dat/leap/cmd/' + args.force_field):
            print "Warning: force field not found! This is likely to cause \
            problems later.\n"
        else:
            ff = amberhome + '/dat/leap/cmd/' + args.force_field

    #Find out which water model we're using
    if args.water_model == 'opc':
        args.water_model = 'leaprc.water.opc'
    elif args.water_model == 'spce':
        args.water_model = 'leaprc.water.spce'
    elif args.water_model == 'tip4':
        args.water_model = 'leaprc.water.tip4pew'

    #do we have nonstandard residues?
    mol_data = {}
    nonstandard_res = {}
    standard_res = util.get_available_res(ff)
    
    #if any structure was not provided in PDB format, we will attempt to create
    #one from what was provided using obabel, choosing a filename that will not
    #overwrite anything in the directory (optionally)
    for structure in args.structures:
        #the "structure" string in the args.structure list will be updated so
        #that it corresponds to the PDB we should use for subsequent steps
        assert os.path.isfile(structure),'%s does not exist\n' % structure
        #"base" is the base filename (no extension) from which others will be derived
        base = util.get_base(structure)
        if os.path.splitext(structure)[-1] != '.pdb':
            outpdb = base + '.pdb'
            if not args.overwrite:
                outpdb = util.get_fname(outpdb)
            try:
                obabel[structure, '-O', outpdb]()
            except Exception as e:
                print 'Cannot create PDB from input, error {0} : {1}. Check \
                {2}. Aborting...\n'.format(e.errno, e.strerror, outpdb)
                sys.exit()
            idx = args.structures.index(structure)
            args.structures[idx] = outpdb
            structure = outpdb
        mol_res = {}
        mol_data[structure] = pdb.simplepdb(structure)
        if not mol_data[structure].has_unique_names() and not mol_data[structure].is_protein():
            mol_data[structure].rename_atoms()
        mol_res[structure] = set(mol_data[structure].mol_data['resname'])
        nonstandard_res[structure] = list(mol_res[structure] - standard_res)

    #if nonstandard residues, do we have the necessary library files? 
    #check for prep, lib, and off; just add the frcmod if there is one
    libs = set([])
    #make an iterator in case we need to get library names from input arg
    if not args.libs:
        args.libs = []
    lig_iter = iter(args.libs)
    for struct,reslist in nonstandard_res.items():
        #track which units you don't have libs for
        orphaned_res = set(reslist)
        base = util.get_base(struct)
        #try any user-provided locations first
        for user_lib in args.libs:
            for ext in ['.lib','.off','.prep']:
                fname = userlib + ext
                if os.path.isfile(fname):
                    set_matches(fname, libs, reslist, orphaned_res,
                            mol_data[struct], True)
        #if residues are still undefined, check the current directory too
        if orphaned_res:
            local_libs = [name for name in glob.glob('*.lib') +
                    glob.glob('*.off') + glob.glob('*.prep')]
            for lib in local_libs:
                set_matches(lib, libs, reslist, orphaned_res, mol_data[struct])
   
        is_protein = mol_data[struct].is_protein()
        #for now, require that the ligand be provided separately from the protein -
        #that way we don't need to worry about differentiating between modified
        #residues (or other things we don't want to strip out of the protein) and
        #small molecules we can parametrize with antechamber
        assert not (is_protein and orphaned_res), \
        "Undefined units %s in protein - check for modified residues, ions, or \
cofactors\n" % ' '.join(orphaned_res)

        if is_protein and not args.noh: 
            fname = base + '_amber.pdb'
            pdb4amber['-y', '-i', struct, '-o', fname] & FG
            idx = args.structures.index(struct)
            args.structures[idx] = fname
            if not args.uninteractive:
                raw_input('Read the above messages and then press any key to continue...\n')
            mol_data[fname] = pdb.simplepdb(fname)

        assert len(orphaned_res)<2, "%s has multiple ligands; break them into \
        separate files to process with antechamber\n" % struct

        #if we're handling a ligand and don't have library files, we will need at 
        #least the pdb-formatted data and a mol2 from which we can derive gasteiger 
        #charges for antechamber; make these with babel and find the net charge
        if orphaned_res:
            #"molname" will be the name of the unit for AMBER
            #TODO: check whether, if there are multiple ligands to be fit in
            #antechamber, the user has provided unit names for all of them or
            #they have distinct residue names 
            try:
                molname = next(lig_iter)[:3].upper()
            except StopIteration:
                molname = list(orphaned_res)[0]
            mol_data[struct].sanitize()
            mol_data[struct].set_resname(molname)
            tempname = base + '_temp.pdb'
            ligname = base + '_amber.pdb'
            if not args.overwrite:
                tempname = util.get_fname(tempname)
                ligname = util.get_fname(ligname)
            if os.path.isfile(ligname):
                os.remove(ligname)
            mol2 = base + '_amber.mol2'
            #create a PDB that has unique atom names, hydrogens, all HETATM
            #records, element names, and the correct residue name
            if not args.noh:
                mol_data[struct].writepdb(tempname)
                obabel[tempname, '-O', ligname, '-h']()
                os.remove(tempname)
                mol_data[struct] = pdb.simplepdb(ligname)
                mol_data[struct].sanitize()
                mol_data[struct].set_recordname('HETATM')
                os.remove(ligname)
                mol_data[struct].writepdb(ligname)
            else:
                mol_data[struct].writepdb(ligname)
            idx = args.structures.index(struct)
            args.structures[idx] = ligname
            mol_data[ligname] = mol_data[struct]
            #get gasteiger charges
            obabel[ligname, '-O', mol2]()
            net_charge = util.get_charge(mol2)
            #run antechamber
            print 'Parametrizing unit %s with antechamber.\n' % ' '.join(orphaned_res)
            do_antechamber(ligname, net_charge, ff, molname, base)
            #add the libraries created in the last step to the libs list
            libs.add(base + '.lib')
            libs.add(base + '.frcmod')

    #ok, now we can be pretty sure we know what to do and that we are able to do it
    #create complex if there are multiple structures
    if len(args.structures) > 1:
        complex_name = args.out_name + '.pdb'
        start_atom, start_res = 1,1
        if os.path.isfile(complex_name):
            os.remove(complex_name)
        print args.structures
        print mol_data
        mol_data[args.structures[0]].writepdb(complex_name, mol_data.values())
    #if only one structure, just use the files output in the steps above
    else:
        complex_name = args.structures[0]
    base = util.get_base(complex_name)
    #make initial parameters files
    make_amber_parm(complex_name, base, ff, 'complex', args.water_model, args.water_dist, libs)
    #run the two minimization and two pre-production  MDs
    if not args.parm_only: do_amber_preproduction(complex_name, base, args, ff)
    #run the final production MD
    if args.run_prod_md: do_amber_production(base)
