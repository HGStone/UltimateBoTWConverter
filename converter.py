from pathlib import Path
from bcml.install import open_mod
from bcml.dev import convert_mod
from bcml import util
from subprocess import run
from os.path import sep, splitext
from glob import glob
from urllib.request import urlopen, urlretrieve
from io import BytesIO
from zipfile import ZipFile
from platform import system 
from bflim_convertor import bntx_dds_injector as bntx
from time import sleep

import shutil
import bars_converter as barstool
import bcf_converter as sound
import argparse
import oead
import traceback


# Construct an argument parser
parser = argparse.ArgumentParser(description="Converts mods in BNP format using BCML's converter, complemented by some additional tools")
parser.add_argument("bnp", nargs='+')
args = parser.parse_args()

# Supported formats
supp_formats = [".sbfres", ".sbitemico", ".hkcl", ".bars", ".bfstm", ".bflim", ".sblarc"]

def confirm_prompt(question: str) -> bool:
    # https://gist.github.com/garrettdreyfus/8153571
    reply = None
    while reply not in ("", "y", "n"):
        reply = input(f"{question} (Y/n): ").lower()
    return (reply in ("", "y"))

def extract_sarc(sarc: oead.Sarc, sarc_path: Path) -> None:
    # Extract the data from a SARC file
    Path(sarc_path).mkdir(exist_ok=True)
    for file in sarc.get_files():
        if not Path(sarc_path / file.name).parent.exists():
            Path(sarc_path / file.name).parent.mkdir(parents=True)
        Path(sarc_path / file.name).write_bytes(file.data)

def write_sarc(sarc: oead.Sarc, sarc_path: Path, sarc_file: Path) -> None:
    # Overwrite the SARC file with the modified files
    new_sarc = oead.SarcWriter(endian=oead.Endianness.Little)
    for file in sarc_path.rglob("*.*"):
        new_file = f'{file}'.split(f"{sarc_file.name}{sep}")[1].replace("\\", "/")
        new_sarc.files[new_file] = file.read_bytes()
    if sarc_file.suffix == ".pack":
        sarc_file.write_bytes(new_sarc.write()[1])
    else:
        sarc_file.write_bytes(oead.yaz0.compress(new_sarc.write()[1]))

def convert_fres(sbfres: Path) -> None:
    # Convert sbfres files
    if not Path('BfresPlatformConverter').exists():
        # Code adapted from https://gist.github.com/hantoine/c4fc70b32c2d163f604a8dc2a050d5f6
        # Extract BfresPlatformConverter if it's not already in the system
        print("Downloading BfresPlatformConverter...")
        http_response = urlopen('https://gamebanana.com/dl/485626')
        zipfile = ZipFile(BytesIO(http_response.read()))
        zipfile.extractall(path='BfresPlatformConverter')

    # If our FRES file is a texture, use the Tex2 file which should be in the same folder...
    if '.Tex1' in sbfres.suffixes:
        bfres = util.unyaz_if_needed(sbfres.read_bytes())
        tex2 = Path(f'{sbfres.parent}{sep}{sbfres.name.replace("Tex1", "Tex2")}')
        if tex2.exists():
            tex2b = util.unyaz_if_needed(tex2.read_bytes())
            tex2.write_bytes(tex2b)
            sbfres.write_bytes(bfres)
    # ...else, work with our FRES file only
    else:
        bfres = util.unyaz_if_needed(sbfres.read_bytes())
        sbfres.write_bytes(bfres)

    # Convert the FRES file, formatting the path to the converter according to the OS
    if system() == "Windows":
        run(["BfresPlatformConverter\\BfresPlatformConverter.exe", sbfres])
    else:
        run(['mono', "BfresPlatformConverter/BfresPlatformConverter.exe", sbfres])

    # Save our new file
    if sbfres.suffixes == ['.Tex1', '.sbfres']:
        if tex2.exists():
            c_bfres = oead.yaz0.compress(Path(f'SwitchConverted{sep}{sbfres.name.replace("Tex1", "Tex")}').read_bytes())
            sbfres.write_bytes(c_bfres)
            sbfres.rename(Path(f'{sbfres.parent}{sep}{sbfres.name.replace("Tex1", "Tex")}'))
            tex2.unlink()
    elif sbfres.suffixes != ['.Tex2', '.sbfres']:
        c_bfres = oead.yaz0.compress(Path(f'SwitchConverted{sep}{sbfres.name}').read_bytes())
        sbfres.write_bytes(c_bfres)


def convert_havok(actorpack: Path) -> None:
    # Convert havok files unsupported by BCML
    if not Path('HKXConvert').exists() or not Path('HKXConvert.exe').exists():
        # Download HKXConvert if it's not already in the system
        print("Downloading HKXConvert...")
        if system() == "Windows":
            filename, headers = urlretrieve('https://github.com/krenyy/HKXConvert/releases/download/1.0.1/HKXConvert.exe', filename='HKXConvert.exe')
            hkx_c = f".{sep}HKXConvert.exe"
        else:
            filename, headers = urlretrieve('https://github.com/krenyy/HKXConvert/releases/download/1.0.1/HKXConvert', filename='HKXConvert')
            hkx_c = f".{sep}HKXConvert"
        # Make sure we can run the program by setting the correct permissions
        Path(f'{hkx_c}').chmod(0o755)

    # Use the actorpack's name to create a new folder to write its contents in
    actor_path = Path(actorpack.name)
    actor = oead.Sarc(util.unyaz_if_needed(actorpack.read_bytes()))
    extract_sarc(actor, actor_path)

    # Look in the actor pack's files for hkx files.
    hkxs = actor_path.rglob('*.hk*')
    for hkx in hkxs:
        # Convert every hkx found into json, and then to switch
        run([hkx_c, 'hkx2json', hkx])
        hkx.unlink()
        run([hkx_c, 'json2hkx', '--nx', f'{splitext(hkx)[0]}.json'])
        Path(f'{splitext(hkx)[0]}.json').unlink()
    if hkxs:
        # Write the new actor file
        print(f"HKX files converted. Saving {actorpack.name}")
        write_sarc(actor, actor_path, actorpack)

    # Remove the temporary folder
    shutil.rmtree(actor_path)

def convert_bflim(sblarc: Path) -> None:
    # Convert bflim files inside a WiiU sblarc
    blarc = oead.Sarc(util.unyaz_if_needed(sblarc.read_bytes()))
    blarc_path = Path(sblarc.name)

    if any("bflim" in i.name for i in blarc.get_files()):
        # Get the pack file where the sblarc comes from
        stock_pack = util.get_game_file(f"Pack/{sblarc.parent.parent.name}")

        try:
            # If the sblarc is in Bootup.pack, get a stock Common.sblarc
            stock_sblarc = oead.Sarc(stock_pack.read_bytes()).get_file("Layout/Common.sblarc")
            stock_blarc = oead.Sarc(util.unyaz_if_needed(stock_sblarc.data))

        except (oead.InvalidDataError, AttributeError):
            # If the sblarc is in Title.pack, get a stock Title.sblarc
            stock_sblarc = oead.Sarc(stock_pack.read_bytes()).get_file("Layout/Title.sblarc")
            stock_blarc = oead.Sarc(util.unyaz_if_needed(stock_sblarc.data))

        # Get a stock bntx file
        bntx_file = stock_blarc.get_file("timg/__Combined.bntx")
        extract_sarc(blarc, blarc_path)
        Path(blarc_path / bntx_file.name).write_bytes(bntx_file.data)

        for bflim in blarc_path.rglob('*.bflim'):
            # Inject every bflim found into the bntx file
            bntx.tex_inject(blarc_path / bntx_file.name, bflim, False)
            Path(bflim).unlink()
        
        # Write the new blarc file
        write_sarc(blarc, blarc_path, sblarc)

        # Remove the temporary folder
        shutil.rmtree(blarc_path)

def convert_files(file: Path, mod_path: Path) -> None:
    # Convert supported files
    if file.exists() and file.stat().st_size != 0:
        if file.suffix == ".sbfres" or file.suffix == ".sbitemico":
            # Convert FRES files
            if ".Tex2" not in file.suffixes:
                convert_fres(file)

        elif file.suffix == ".sbactorpack":
            # Convert havok files inside actor packs
            actor = oead.Sarc(util.unyaz_if_needed(file.read_bytes()))
            actor_path = Path(file.name)
            if any("hkcl" in i.name for i in actor.get_files()) or any("hkrg" in i.name for i in actor.get_files()):
                convert_havok(file)

        elif file.suffix == ".bars":
            # Convert bars files
            new_bars = barstool.convert_bars(file.read_bytes(), '<', '>')
            file.write_bytes(bytes(new_bars))
            print("Converted " + file.name + "!")

        elif file.suffix == ".bfstm":
            # Convert BFSTM files
            new_bfstm = sound.convFile(file.read_bytes(), "FSTM", '<')
            file.write_bytes(bytes(new_bfstm))

        elif file.suffix == ".pack": #or file.suffix == ".sbeventpack":
            # Convert files inside of pack files
            pack = oead.Sarc(util.unyaz_if_needed(file.read_bytes()))
            pack_path = Path(file.name)
            if any(splitext(i.name)[1] in supp_formats for i in pack.get_files()):
                extract_sarc(pack, pack_path)
                convert_files(pack_path.rglob('*.*'), mod_path)
                write_sarc(pack, pack_path, file)
                shutil.rmtree(pack_path)

        elif file.suffix == ".sblarc":
            # Convert bflim files inside of sblarc files
            convert_bflim(file)

        elif file.suffix == ".hkcl":
            # If there's an hkcl file not in an actorpack, convert it as well
            convert_havok(file)

def clean_up() -> None:
    if Path('HKXConvert').exists():
        Path('HKXConvert').unlink()
    shutil.rmtree('BfresPlatformConverter', ignore_errors=True)
    shutil.rmtree('SwitchConverted', ignore_errors=True)
    shutil.rmtree('WiiUConverted', ignore_errors=True)

def convert(mod: Path) -> None:
    # Open the mod
    mod_path = open_mod(mod)
    files = mod_path.rglob('*.*')
    try: 

        # Run the mod through BCML's automatic converter first 
        warnings = convert_mod(mod_path, False, True)

        # Convert supported files
        for file in files:
            convert_files(file, mod_path)
        
        # Pack the converted mod into a new bnp
        out = mod.with_name(f"{mod.stem}_switch.bnp")
        if Path(out).exists():
            Path(out).unlink()
        x_args = [
            util.get_7z_path(),
            "a",
            out,
            f'{mod_path / "*"}',
        ]
        run(x_args)

        # Write BCML's warning to a file
        if all(i not in warning for warning in warnings for i in supp_formats):
            with open("error.log", "a") as file:
                for warning in warnings:
                    # Write BCML's warning to a file
                    if isinstance(warning, list):
                        for error in warning:
                            if all(i not in error for i in supp_formats):
                                file.write(error + "\n")
                        
                    elif all(i not in warning for i in supp_formats):
                        file.write(warning + "\n")

    except Exception:
        print(traceback.format_exc())
        clean_up()

    finally:
        # Remove the temporary mod_path
        shutil.rmtree(mod_path, ignore_errors=True)

def main() -> None:
    if len(args.bnp) == 1: # one argument
        mods = glob(args.bnp[0])
    else: # more than one argument
    	mods = args.bnp

    downloaded = False
    if Path('BfresPlatformConverter').exists() and (Path('HKXConvert').exists() or Path('HKXConvert.exe').exists()):
        downloaded = True

    # Set BCML to Switch mode
    settings = util.get_settings()
    settings["wiiu"] = False
    util.save_settings()
    
    for mod in mods:
        convert(Path(mod))

    if (Path('BfresPlatformConverter').exists() or Path('HKXConvert').exists() or Path('HKXConvert.exe').exists()) and not downloaded:
        keep = confirm_prompt("Would you like to keep the downloaded files?")
        if not keep:
            clean_up()


if __name__ == "__main__":
    main()      
