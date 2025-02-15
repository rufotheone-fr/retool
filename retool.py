#!/usr/bin/env python

""" retool.py: Creates 1G1R versions of [Redump](http://redump.org/)
and [No-Intro](https://www.no-intro.org) dats.

https://github.com/unexpectedpanda/retool
"""

import datetime
import glob
import os
import re
import sys
import time
import traceback

from itertools import permutations

from modules.classes import Regex, RegionKeys, Stats, TagKeys, Titles
from modules.customfilters import recover_titles_for_custom_filters
from modules.importdata import build_clone_lists, build_regions, build_tags,\
    import_metadata
from modules.output import generate_config, write_dat_file
from modules.parentselection import assign_clones, choose_cross_region_parents
from modules.titleutils import get_title_count, report_stats
from modules.userinput import check_input, import_user_config,\
    import_user_filters
from modules.utils import Font, old_windows, printverbose, printwrap
from modules.xml import dat_to_dict, process_input_dat

# Require at least Python 3.8
assert sys.version_info >= (3, 8)

__version__ = '0.96'

def main(gui_input=''):

    # Enable VT100 escape sequence for Windows 10 Ver. 1607+
    if old_windows() != True and sys.platform.startswith('win'):
        from modules.utils import enable_vt_mode
        enable_vt_mode()

    # Start a timer from when the process started
    start_time = time.time()

    # Splash screen
    print(f'{Font.bold}\nRetool {__version__}{Font.end}')
    print('-----------')

    if len(sys.argv) == 1 and gui_input == '':
        printwrap(
            f'Creates 1G1R versions of Redump ({Font.underline}'
            f'http://redump.org/{Font.end}) and No-Intro '
            f'({Font.underline}https://www.no-intro.org/{Font.end}) dats. '
            f'A new dat file is automatically generated, the original file '
            f'isn\'t altered.', 'no_indent'
        )

        print(
            f'\nusage: {os.path.basename(sys.argv[0])} <input dat/folder> '
            '<options>')

        print(
            f'\nType {Font.bold}{os.path.basename(sys.argv[0])} -h{Font.end} '
            'for all options\n')

    # Generate regions and languages
    region_data = build_regions(RegionKeys())
    languages = '|'.join(region_data.languages_short)

    # Accommodate No-Intro language madness
    no_intro_languages = region_data.languages_short
    no_intro_languages.extend(no_intro_languages)

    no_intro_permutations = []

    for i in permutations(no_intro_languages, 2):
        no_intro_permutations.append('|' + '\+'.join(i))

    no_intro_permutations = ''.join(no_intro_permutations)

    LANGUAGES = languages + no_intro_permutations

    # Regexes
    REGEX = Regex(LANGUAGES)

    # Generate user config files if they're missing
    generate_config(region_data.languages_long, region_data.region_order)

    # Check user input -- if none, or there's an error, available options will
    # be shown
    if gui_input == '':
        user_input = check_input()
    else:
        user_input = gui_input
        if user_input.user_options == ' (-)':
            user_input.user_options = ''

    # Import the user-config.yaml file and assign filtered languages and custom
    # region order.
    user_input = import_user_config(region_data, user_input)

    # Compensate for No-Intro using "United Kingdom", and Redump using "UK"
    if 'UK' in user_input.user_region_order:
        uk_index = user_input.user_region_order.index('UK')
        user_input.user_region_order[uk_index + 1:uk_index + 1] = ['United Kingdom']
        uk_index = region_data.all.index('UK')
        region_data.all[uk_index + 1:uk_index + 1] = ['United Kingdom']
        if 'UK' in region_data.implied_language:
            region_data.implied_language['United Kingdom'] = 'En'

    # Based on region counts from redump.org. Used later to speed up processing
    # through altering the order.
    PRIORITY_REGIONS = [
        'USA', 'Japan', 'Europe', 'Germany', 'Poland', 'Italy',
        'France', 'Spain', 'Netherlands', 'Russia', 'Korea']

    # Generate tag strings
    user_input.tag_strings = build_tags(TagKeys())

    # An easy way to always enable dev mode, which enables -x and --error by
    # default. This makes it easier to update clone lists, through diffing a new
    # output dat against the previous one.
    if os.path.isfile('.dev'):
        printverbose(
            user_input.verbose,
            f'{Font.warning_bold}* Operating in dev mode{Font.end}')

    # Process the input file or folder
    if os.path.isdir(user_input.input_file_name) == True:
        is_folder = True
        dat_files = glob.glob(
            os.path.abspath(user_input.input_file_name) + '/*.dat')
        print('Processing folder...')
    else:
        is_folder = False
        dat_files = {user_input.input_file_name}

    file_count = len(dat_files)

    for i, dat_file in enumerate(dat_files):
        if file_count > 1:
            print(f'\n{Font.underline}Processing file '
                  f'{i+1}/{len(dat_files)}{Font.end}\n')

        # Process and get the details we need from the input file
        input_dat = process_input_dat(dat_file, is_folder)

        if input_dat == 'end_batch':
            continue

        # Import the system's clone lists, if they exist
        input_dat.clone_lists = build_clone_lists(input_dat)

        # Make sure this version of Retool can deal with the imported clone list
        if input_dat.clone_lists is not None:
            if input_dat.clone_lists.min_version != {}:
                if float(input_dat.clone_lists.min_version) > float(__version__):
                    out_of_date = ''

                    while not (out_of_date == 'y' or out_of_date == 'n'):
                        printwrap(
                            f'{Font.warning_bold}* This clone list requires Retool '
                            f'{str(input_dat.clone_lists.min_version)} or higher. '
                            'Behaviour might be unpredictable. Please update '
                            'Retool to fix this.',
                            'error'
                        )

                        out_of_date = input(f'\n  Continue? (y/n) {Font.end}')

                    if out_of_date == 'n':
                        sys.exit()
                    else:
                        print('')

        # Import scraped Redump metadata for titles
        input_dat.metadata = import_metadata(input_dat)

        # Import custom global filters
        if os.path.isfile(f'user-filters/global.yaml'):
            user_filters = import_user_filters('global', 'global')
            user_input.global_excludes = user_filters.data['exclude']
            user_input.global_includes = user_filters.data['include']

            if type(user_input.global_excludes) is str: user_input.global_excludes = []
            if type(user_input.global_includes) is str: user_input.global_includes = []
        else:
            user_input.global_excludes = []
            user_input.global_includes = []

        # Import custom system filters
        if 'PlayStation Portable' in input_dat.name:
            if 'no-intro' in input_dat.url:
                    filter_file = 'Sony - PlayStation Portable (No-Intro)'
            elif 'redump' in input_dat.url:
                filter_file = 'Sony - PlayStation Portable (Redump)'
        else:
            filter_file = input_dat.name

        if os.path.isfile(f'user-filters/{filter_file}.yaml'):
            user_filters = import_user_filters(filter_file, 'system')
            user_input.system_excludes = user_filters.data['exclude']
            user_input.system_includes = user_filters.data['include']

            if type(user_input.system_excludes) is str: user_input.system_excludes = []
            if type(user_input.system_includes) is str: user_input.system_includes = []
        else:
            user_input.system_excludes = []
            user_input.system_includes = []

        # Check if the dat is numbered
        dat_numbered = False

        if 'no-intro' in input_dat.url.lower():
            print(
                '* Checking if the input dat is numbered... ', sep=' ', end='', flush=True)

            dat_numbered = True

            for line in input_dat.soup.find_all('game', {'name': re.compile('.*')}):
                if not re.search('game.*?name="([0-9]|x|z)([0-9]|B)[0-9]{2,2} - ', str(line)):
                    dat_numbered = False

            if dat_numbered == False:
                print('this isn\'t a numbered dat.')
            else:
                print('this is a numbered dat.')

        # Get the stats from the original soup object before it's changed later
        print('* Gathering stats... ', sep=' ', end='', flush=True)
        original_title_count = len(input_dat.soup.find_all('game'))

        stats = Stats(original_title_count)
        print('done.')

        # Provide dat details to reassure the user the correct file is being processed
        print(f'\n|  {Font.bold}DAT DETAILS{Font.end}')
        print(f'|  Description: {input_dat.description}')
        print(f'|  Author: {input_dat.author}')
        print(f'|  URL: {input_dat.url}')
        print(f'|  Version: {input_dat.version}\n')

        # For performance, change the region order so titles with a lot of regions are
        # processed first, and unknown regions are processed last. This doesn't affect
        # the user's region order when it comes to title selection.
        processing_region_order = [
            x for x in user_input.user_region_order if x in PRIORITY_REGIONS]
        processing_region_order.extend(
            [x for x in user_input.user_region_order if x not in PRIORITY_REGIONS and x != 'Unknown'])
        if 'Unknown' in user_input.user_region_order:
            processing_region_order.append('Unknown')

        # Set up a dictionary to record the title names that have been removed, for
        # when the user sets --log
        user_input.removed_titles = {}

        # Convert each region's XML to dicts so we can more easily work with the data,
        # and determine each region's parent
        titles = Titles()

        removes_found = set()
        categories_found = set()

        for region in processing_region_order:
            if old_windows() != True:
                print(
                    f'* Finding titles in regions... {region}',
                    sep='', end='\r', flush=True
                )
            titles.regions[region] = dat_to_dict(
                region, region_data, input_dat, user_input,
                removes_found, categories_found, dat_numbered, REGEX)

            if old_windows() != True:
                sys.stdout.write("\033[K")

        if input_dat.clone_lists != None:
            # Deal with removes
            missing_removes = {
                remove for remove in input_dat.clone_lists.removes if remove not in removes_found}

            for remove in missing_removes:
                printverbose(
                    user_input.verbose,
                    f'{Font.warning_bold}* Title in removes list not found in dat: '
                    f'{remove}{Font.end}')

            stats.remove_count = len(removes_found)

            # Deal with category changes
            missing_categories = {
                category for category in input_dat.clone_lists.categories if category not in categories_found}

            for category in missing_categories:
                printverbose(
                    user_input.verbose,
                    f'{Font.warning_bold}* Title in categories list not found in dat: '
                    f'{category}{Font.end}')

        print('* Finding titles in regions... done.')

        # Combine all regions' titles and choose a parent based on region order
        print('* Finding parents across regions... ', sep='', end='\r', flush=True)

        titles = choose_cross_region_parents(titles, user_input, dat_numbered, REGEX)

        print('* Finding parents across regions... done.')

        # Recover titles for global/system includes
        recovered_groups = {}

        if user_input.no_filters == False:
            recovered_groups = recover_titles_for_custom_filters(user_input, input_dat, dat_numbered, recovered_groups, region_data, REGEX)

        # Process clone lists
        if input_dat.clone_lists != None:
            print('* Assigning clones from clone lists... ', sep='', end='\r', flush=True)

            titles = assign_clones(titles, input_dat, region_data, user_input, dat_numbered, REGEX)

            if old_windows() != True:
                sys.stdout.write("\033[K")
            print('* Assigning clones from clone lists... done. ') # Intentional trailing space for Win 7

        # Get the clone count
        stats.clone_count = 0
        for group, disc_titles in titles.all.items():
            for disc_title in disc_titles:
                if disc_title.cloneof != '':
                    stats.clone_count += 1

        if bool(titles.all) == False:
            stats.final_title_count = 0
        else:
            # Get final title count
            if user_input.legacy == False:
                stats.final_title_count = get_title_count(titles, is_folder) - stats.clone_count
            else:
                stats.final_title_count = get_title_count(titles, is_folder)

        if stats.final_title_count != 0:
            # Name the output file
            # Create the output folder if it doesn't exist
            if user_input.output_folder_name != '' and not os.path.exists(user_input.output_folder_name):
                print(f'* Creating folder "{Font.bold}{user_input.output_folder_name}{Font.end}"')
                os.makedirs(user_input.output_folder_name)

            if 'PlayStation Portable' in input_dat.name:
                if 'no-intro' in input_dat.url:
                    input_dat.name = input_dat.name + ' (No-Intro)'
                else:
                    input_dat.name = input_dat.name + ' (Redump)'

            # Merge in includes if there are any
            if recovered_groups != {}:
                for key, values in recovered_groups.items():
                    if key not in titles.all:
                        titles.all[key] = []

                    for value in values:
                        titles.all[key].append(value)
                        stats.recovered_count = stats.recovered_count + 1

            stats.final_title_count = stats.final_title_count + stats.recovered_count

            output_file_name = (
                os.path.join(
                    user_input.output_folder_name,
                    f'{input_dat.name} ({input_dat.version}) '
                    f'(Retool {datetime.datetime.now().strftime("%Y-%m-%d %H-%M-%SS")[:-1]}) ({str("{:,}".format(stats.final_title_count))}){user_input.user_options}.dat'))

            # Write the output dat file
            write_dat_file(input_dat, user_input, output_file_name, stats, titles, dat_numbered, __version__)

            # Report stats
            stats = Stats(original_title_count, user_input, stats.final_title_count, stats.clone_count, stats.recovered_count)
            report_stats(stats, titles, user_input, input_dat)

        else:
            print(f'{Font.warning}\n* No titles found. No dat file has been created.{Font.end}')

        # Start the loop again if processing a folder
        if is_folder == True: continue

    # Stop the timer
    stop_time = time.time()
    total_time_elapsed = str('{0:.2f}'.format(round(stop_time - start_time,2)))

    # Set the summary message if input was a folder and files were found
    if is_folder == True:
        if file_count > 0:
            if file_count == 1:
                file_noun = 'file'
            else:
                file_noun = 'files'

            file_count = str('{:,}'.format(file_count))

            finish_message = (
                f'{Font.success}* Finished processing {file_count} {file_noun} in the '
                f'{Font.bold}"{os.path.abspath(user_input.input_file_name)}{Font.success}" folder in '
                f'{total_time_elapsed}s. 1G1R dats have been created in the '
                f'{Font.bold}"{os.path.abspath(user_input.output_folder_name)}"{Font.success} folder.{Font.end}'
                )
        else:
            # Set the summary message if no files were found in input folder
            finish_message = (
                f'{Font.warning}* No files found to process in the '
                f'{Font.bold}"{user_input.input_file_name}"{Font.warning} folder.{Font.end}'
                )
    else:
        if 'output_file_name' in locals():
            # Set the summary message if input was a single file
            finish_message = (
                f'{Font.success}* Finished adding '
                f'{str("{:,}".format(stats.final_title_count))}'
                f' unique titles to "{Font.bold}{os.path.abspath(output_file_name)}" '
                f'{Font.success}in {total_time_elapsed}s.{Font.end}'
                )
        else:
            finish_message = ''

    # Print the summary message
    print()
    printwrap(f'{finish_message}')
    print()

    return

def retool_version():
    return __version__


if __name__ == '__main__':
    try:
        main()
    except Exception:
        print(f'{Font.error_bold}\n\n* Unexpected error:\n\n{Font.end}')
        traceback.print_exc()
        input(f'{Font.error_bold}\n\nPress any key to quit Retool{Font.end}')