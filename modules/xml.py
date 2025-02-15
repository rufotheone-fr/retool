import datetime
import functools
import html
import os
import re
import sys

from lxml import etree
from bs4 import BeautifulSoup

from modules.classes import Dat, DatNode
from modules.customfilters import custom_exclude_filters
from modules.parentselection import choose_parent
from modules.titleutils import get_raw_title
from modules.utils import Font, old_windows, printverbose, printwrap


def convert_clrmame_dat(input_dat, is_folder):
    """ Converts CLRMAMEPro dat format to LogiqX dat format """

    input_dat.contents = ''.join(input_dat.contents)

    clrmame_header = re.search('^clrmamepro \($.*?^\)$', input_dat.contents, re.M|re.S)

    def header_details(find_string, replace_string):
        """ Gets values for CLRMAMEPro dat header details """

        search_string = re.search(find_string, clrmame_header[0])

        if search_string != None:
            return re.sub(
                replace_string,
                '',
                search_string.group(0)).strip()
        else:
            return ''

    dat_name = header_details(re.compile('.*?name.*'), 'name |(\")')
    dat_description = header_details(
        re.compile('.*?description.*'), 'description |(\")')
    dat_category = header_details(re.compile('.*?category.*'), 'category |(\")')
    dat_version = header_details(re.compile('.*?version.*'), 'version |(\")')
    dat_author = header_details(re.compile('.*?author.*'), 'author |(\")')

    convert_dat = []

    convert_dat.append(
        '<?xml version="1.0"?>\n\
        <!DOCTYPE datafile PUBLIC "-//Logiqx//DTD ROM Management Datafile//EN" \
            "http://www.logiqx.com/Dats/datafile.dtd"><datafile>\n\t<header>')
    convert_dat.append(f'\t\t<name>{dat_name}</name>')
    convert_dat.append(f'\t\t<description>{dat_description}</description>')
    convert_dat.append(f'\t\t<version>{dat_version}</version>')
    convert_dat.append(f'\t\t<author>{dat_author}</author>\n\t</header>')

    # Now work through each of the title details
    dat_contents = re.findall('^game \($.*?^\)$', input_dat.contents, re.M|re.S)
    if dat_contents:
        for item in dat_contents:
            xml_node = re.split('\n', item)
            regex = re.sub('name |(\")', '', xml_node[1].strip())
            convert_dat.append(
                f'\t<game name="{regex}">'
                f'\n\t\t<category>{dat_category}</category>\n\t\t<description>'
                f'{regex}</description>')
            for node in xml_node:
                if node.strip().startswith('rom'):
                    node = node
                    node = re.sub('^rom \( name ', '<rom name="', node.strip())
                    node = re.sub(' size ', '" size="', node.strip())
                    node = re.sub(' crc ', '" crc="', node.strip())
                    node = re.sub(' md5 ', '" md5="', node.strip())
                    node = re.sub(' sha1 ', '" sha1="', node.strip())
                    node = re.sub(' \)$', '" />', node.strip())
                    convert_dat.append('\t\t' + node)
            convert_dat.append('\t</game>')
        convert_dat.append('</datafile>')

        convert_dat = '\n'.join(convert_dat)
    else:
        printwrap(
            f'{Font.error_bold} * Error: {Font.error}file isn\'t Logiqx XML or '
            f'CLRMAMEPro dat.{Font.end}', 'error')
        if is_folder == False:
            sys.exit()
        else:
            return 'end_batch'
    return Dat(convert_dat, dat_name, dat_description, dat_version, dat_author)


def dat_to_dict(region, region_data, input_dat, user_input, removes_found, categories_found, dat_numbered, REGEX):
    """ Converts an input dat file to a dict """

    # Find all titles in the soup object that belong to the current region
    if region == 'Unknown':
        refined_region_xml = input_dat.soup.find_all(
            'game', {'name': re.compile(
                '^(?!.*(\(.*?(' + '|'.join(region_data.all).replace(
                    '|Unknown','') + ').*?\))).*(.*)')})
    else:
        # Rough region selection first, as this speeds up processing larger files.
        region_xml = input_dat.soup.find_all(
            'game', {'name': lambda x: x and region in x})

        # Now refine the region selection
        refined_region_xml = []
        for node in region_xml:
            if re.search('game.*?name=.*?\((.*?,){0,} {0,}' + region + '(,.*?){0,}\)', str(node)) != None:
                refined_region_xml.append(node)
        region_xml = None

    progress = 0
    progress_old = 0
    progress_total = len(refined_region_xml)

    # Create a dict to store groups of related titles in
    groups = {}

    # Convert the XML to dict
    for node in refined_region_xml:
        progress += 1
        progress_percent = int(progress/progress_total*100)

        if progress_old != progress_percent:
            if old_windows() != True:
                sys.stdout.write("\033[K")
                print(
                        f'* Finding titles in regions... {region} [{progress_percent}%]',
                        sep='', end='\r', flush=True
                    )
            else:
                print(
                        f'* Finding titles in regions... {region} [{progress_percent}%]',
                        end='\r', flush=True
                    )

        # Drop XML nodes with custom strings the user has chosen to exclude
        if user_input.no_filters == False:
            # System excludes are overriden by system includes.
            # Global excludes are overriden by global and system includes.
            if custom_exclude_filters(
                user_input,
                node,
                user_input.system_excludes,
                'Custom system filter excludes',
                user_input.system_includes) == True: continue
            if custom_exclude_filters(
                user_input,
                node,
                user_input.global_excludes,
                'Custom global filter excludes',
                user_input.global_includes + user_input.system_includes) == True: continue

        # Drop XML nodes that don't have roms or disks specified
        if (
            node.rom == None
            and node.disk == None
            and user_input.empty_titles != True):
            continue

        # Drop XML nodes that don't have at least one hash specified for roms
        if (
            'crc' not in str(node.rom)
            and 'md5' not in str(node.rom)
            and 'sha1' not in str(node.rom)
            and user_input.empty_titles != True
        ):
            continue

        # Get the group name for the current node, then add it to the groups list
        if dat_numbered == False:
            group_name = get_raw_title(node.description.parent['name'])
        else:
            group_name = get_raw_title(node.description.parent['name'][7:])

        if group_name not in groups:
            groups[group_name] = []

         # Add the current title to the group
        groups[group_name].append(
            DatNode(node, region, region_data, user_input, input_dat, dat_numbered, REGEX))

        if input_dat.clone_lists != None:
            # Deal with removes
            if input_dat.clone_lists.removes != None:
                for key, value in input_dat.clone_lists.removes.items():
                    if 'match' not in value:
                        value['match'] = 'tag free'

                    remove_check = False

                    for disc_title in groups[group_name]:
                        if (
                            disc_title.tag_free_name_lower == key.lower()
                            and value['match'] == 'tag free'
                            ) or (
                                disc_title.full_name_lower == key.lower()
                                and value['match'] == 'full'
                            ) or (
                                disc_title.short_name_lower == key.lower()
                                and value['match'] == 'short'
                            ):
                                remove_check = True
                                removes_found.update([key])

                                if 'Removes' not in user_input.removed_titles:
                                    user_input.removed_titles['Removes'] = []
                                user_input.removed_titles['Removes'].append(disc_title.full_name)
                                if disc_title in groups[group_name]: groups[group_name].remove(disc_title)

            # Deal with category changes
            if input_dat.clone_lists.categories != None:
                for key, value in input_dat.clone_lists.categories.items():
                    if 'match' not in value:
                        value['match'] = 'tag free'

                    for disc_title in groups[group_name]:
                        if (
                            disc_title.tag_free_name_lower == key.lower()
                            and value['match'] == 'tag free'
                            ) or (
                                disc_title.full_name_lower == key.lower()
                                and value['match'] == 'full'
                            ) or (
                                disc_title.short_name_lower == key.lower()
                                and value['match'] == 'short'
                            ):
                                disc_title.categories = value['categories']
                                categories_found.update([key])

                                if 'Categories' not in user_input.removed_titles:
                                    user_input.removed_titles['Categories'] = []
                                user_input.removed_titles['Categories'].append(disc_title.full_name)

                                # Check if the (Demo) tag is missing, and add it if so
                                if 'Demos' in disc_title.categories and '(Demo' not in disc_title.full_name:
                                    if disc_title in groups[group_name]:
                                        groups[group_name].remove(disc_title)
                                        if group_name + ' (Demo)' not in groups:
                                            groups[group_name + ' (Demo)'] = []
                                        groups[group_name + ' (Demo)'].append(disc_title)

        # Filter categories, if the option has been turned on
        def exclude_categories(category, regexes=[]):
            if hasattr(user_input, 'no_' + category.lower().replace('-', '_').replace(' ', '_')):
                if getattr(user_input, 'no_' + category.lower().replace('-', '_').replace(' ', '_')) == True:
                    for disc_title in groups[group_name]:
                        for disc_category in disc_title.categories:
                            if disc_category == category:
                                if category not in user_input.removed_titles:
                                    user_input.removed_titles[category] = []
                                    user_input.recovered_titles[category] = []
                                user_input.removed_titles[category].append(disc_title.full_name)
                                user_input.recovered_titles[category].append(disc_title)
                                if disc_title in groups[group_name]: groups[group_name].remove(disc_title)
                                return True
                        if regexes != []:
                            for regex in regexes:
                                if re.search(regex, disc_title.full_name) != None:
                                    if category not in user_input.removed_titles:
                                        user_input.removed_titles[category] = []
                                        user_input.recovered_titles[category] = []
                                    user_input.removed_titles[category].append(disc_title.full_name)
                                    user_input.recovered_titles[category].append(disc_title)
                                    if disc_title in groups[group_name]: groups[group_name].remove(disc_title)
                                    return True

        if exclude_categories('Add-Ons') == True: continue
        if exclude_categories('Applications', REGEX.programs) == True: continue
        if exclude_categories('Audio') == True: continue
        if exclude_categories('Bad Dumps', [REGEX.bad]) == True: continue
        if exclude_categories('Bonus Discs') == True: continue
        if exclude_categories('Console', [REGEX.bios]) == True: continue
        if exclude_categories('Coverdiscs') == True: continue
        if exclude_categories('Demos', REGEX.demos) == True: continue
        if exclude_categories('Educational') == True: continue
        if exclude_categories('Manuals', REGEX.manuals) == True: continue
        if exclude_categories('Multimedia') == True: continue
        if exclude_categories('Pirate', [REGEX.pirate]) == True: continue
        if exclude_categories('Preproduction', REGEX.preproduction) == True: continue
        if exclude_categories('Promotional', REGEX.promotional) == True: continue
        if exclude_categories('Unlicensed', REGEX.unlicensed) == True: continue
        if exclude_categories('Video', REGEX.video) == True: continue

        # Filter languages, if the option has been turned on
        if user_input.filter_languages == True:
            for disc_title in groups[group_name]:
                language_found = False

                for language in user_input.user_languages:
                    if bool(re.search(language, disc_title.languages)) == True:
                        language_found = True

                    # Handle regions with no languages specified
                    if disc_title.languages == '':
                        # Handle the "Asia" region
                        if (
                            'Asia' in disc_title.regions
                            and (
                                language == region_data.languages_key['English']
                                or language == region_data.languages_key['Chinese']
                                or language == region_data.languages_key['Japanese']
                            )):
                                language_found = True
                        # Handle Hong Kong and Taiwan
                        elif (
                            (
                                'Hong Kong' in disc_title.regions
                                or 'Taiwan' in disc_title.regions
                            )
                            and (
                                language == region_data.languages_key['Chinese']
                                or language == region_data.languages_key['English']
                            )):
                                language_found = True
                        # Handle Latin America
                        elif (
                            'Latin America' in disc_title.regions
                            and (
                                language == region_data.languages_key['Spanish']
                                or language == region_data.languages_key['Portuguese']
                            )):
                                language_found = True
                        # Handle South Africa
                        elif (
                            'South Africa' in disc_title.regions
                            and (
                                language == region_data.languages_key['Afrikaans']
                                or language == region_data.languages_key['English']
                            )):
                                language_found = True
                        # Handle Switzerland
                        elif (
                            'Switzerland' in disc_title.regions
                            and (
                                language == region_data.languages_key['German']
                                or language == region_data.languages_key['French']
                                or language == region_data.languages_key['Italian']
                            )):
                                language_found = True
                        # Handle Ukraine
                        elif (
                            'Ukraine' in disc_title.regions
                            and (
                                language == region_data.languages_key['Ukranian']
                                or language == region_data.languages_key['Russian']
                            )):
                                language_found = True

                if language_found == False and 'Unknown' not in disc_title.regions:
                    if disc_title in groups[group_name]: groups[group_name].remove(disc_title)

                    if 'Filtered languages' not in user_input.removed_titles:
                        user_input.removed_titles['Filtered languages'] = []
                        user_input.recovered_titles['Filtered languages'] = []

                    user_input.removed_titles['Filtered languages'].append(disc_title.full_name)
                    user_input.recovered_titles['Filtered languages'].append(disc_title)

        progress_old = progress_percent

    # Remove the nodes from the soup object so processing other regions is quicker.
    if old_windows() != True:
        print(
                f'* Finding titles in regions... {region} [Finishing up...]',
                sep='', end='\r', flush=True
            )
    else:
        print(
            f'* Finding titles in regions... {region} [Finishing up...]',
            flush=True
        )

    for node in refined_region_xml:
        node.decompose()

        # Process the overrides, which take titles out of existing groups, put them into
        # others, and set fake short names
        #
        # Also process conditional overrides for when renames get funky depending on region
        # ordering. For example, Bishi Bashi Special (Europe) contains Bishi Bashi Special
        # (Japan) and Bishi Bashi Special 2 (Japan). The fact that the first two titles have the
        # same name but different content means a conditional override is required.
        if input_dat.clone_lists != None:
            if input_dat.clone_lists.overrides != None:
                def override(value, titles, override_group):
                    for title in titles:
                        if (
                            title.tag_free_name_lower == key.lower()
                            and value['match'] == 'tag free'
                            ) or (
                                title.full_name_lower == key.lower()
                                and value['match'] == 'full'
                            ):
                            title.short_name = value['new group']
                            title.short_name_lower = override_group
                            title.group = override_group
                            if override_group not in groups:
                                groups[override_group] = []
                            groups[override_group].append(title)
                            groups[get_raw_title(key)].remove(title)


                for key, value in input_dat.clone_lists.overrides.items():
                    if 'match' not in value:
                        value['match'] = 'tag free'

                    if get_raw_title(key) not in groups:
                        groups[get_raw_title(key)] = []

                    if 'condition' in value:
                        if re.search('\((.*?,){0,} {0,}' + region + '(,.*?){0,}\)', key) != None:

                            # Check that the current region is available in the user's region order
                            higher_regions = []

                            for i, another_region in enumerate(user_input.user_region_order):
                                higher_region_name = value['condition']['region']

                                if another_region in higher_region_name:
                                    higher_regions.append(i)

                            if higher_regions != []:
                                lower_regions = []
                                conditional_override = {}

                                # Check that the specified lower regions are available in the user's region order
                                for i, another_region in enumerate(user_input.user_region_order):
                                    for lower_region in value['condition']['higher than']:
                                        if another_region == lower_region:
                                            lower_regions.append(i)

                                if len(lower_regions) > 0:
                                    for higher_region in higher_regions:
                                        conditional_override[higher_region] = 0

                                        for lower_region in lower_regions:
                                            if higher_region < lower_region:
                                                conditional_override[higher_region] += 1

                                        # If so, reassign the group and short_name
                                        if (
                                            conditional_override[higher_region] == len(lower_regions)
                                            and conditional_override[higher_region] > 0
                                            ):

                                            try:
                                                titles_temp = groups[get_raw_title(key)].copy()
                                                override(value, titles_temp, value['new group'].lower())

                                            except:
                                                printverbose(
                                                    user_input.verbose,
                                                    f'{Font.warning}* Conditional override title not found in dat or current region: '
                                                    f'{Font.warning_bold}{key}{Font.end}')

                                        # Otherwise, if the region is lower and there's an "else group" property,
                                        # file the title into that group with the same short_name
                                        elif 'else group' in value['condition']:
                                            try:
                                                titles_temp = groups[get_raw_title(key)].copy()
                                                override(value, titles_temp, value['condition']['else group'].lower())
                                            except:
                                                printverbose(
                                                    user_input.verbose,
                                                    f'{Font.warning}* Conditional override title not found in dat or current region: '
                                                    f'{Font.warning_bold}{key}{Font.end}')
                    else:
                        try:
                            if re.search('\((.*?,){0,} {0,}' + region + '(,.*?){0,}\)', key) != None:
                                override(value, groups[get_raw_title(key)].copy(), value['new group'].lower())

                        except:
                            printverbose(
                                user_input.verbose,
                                f'{Font.warning}* Override title not found in dat or current region: '
                                f'{Font.warning_bold}{key}{Font.end}')

    # Identify the parents for the region
    for group, titles in groups.items():
        if (
            'Dreamcast' in input_dat.name
            or 'Saturn' in input_dat.name
            or 'Sega CD' in input_dat.name
            or 'Panasonic - 3DO' in input_dat.name):
            ring_code = True
        else:
            ring_code = False

        titles = choose_parent(titles, region_data, user_input, dat_numbered, REGEX, ring_code)

    return groups


def process_input_dat(dat_file, is_folder, gui=False):
    """ Prepares input dat file and converts to an object

    Returns a Dat object with the following populated:

    .name
    .description
    .version
    .author
    .url
    .soup

    Removes the following from a Dat object:

    .contents
    """

    if is_folder == True:
        next_status = ' Skipping file...'
    else:
        next_status = ''

    if gui == False:
        printwrap(f'* Reading dat file: "{Font.bold}{os.path.abspath(dat_file)}{Font.end}"')
    try:
        with open(dat_file, 'r', encoding='utf8') as input_file:
            if gui == False:
                print('* Validating dat file... ', sep=' ', end='', flush=True)
            input_dat = Dat()
            input_dat.contents = input_file.readlines()
    except OSError as e:
        printwrap(
            f'{Font.error_bold}* Error: {Font.error}{str(e)}.{Font.end}{next_status}',
            'error')
        if is_folder == False:
            raise
        else:
            return 'end_batch'

    # Check the dat file format -- if it's CLRMAMEPro format, convert it to LogiqX
    if 'clrmamepro' in input_dat.contents[0]:
        if gui == False:
            print('file is a CLRMAMEPro dat file.')
        input_dat = convert_clrmame_dat(input_dat, is_folder)

        # Go to the next file in a batch operation if something went wrong.
        if input_dat == 'end_batch': return
    else:
        # Exit if there are entity or element tags to avoid abuse
        abuse_tags = ['<!ENTITY', '<!ELEMENT']
        for abuse_tag in abuse_tags:
            if bool(list(filter(lambda x: abuse_tag in x, input_dat.contents))) == True:
                print('failed.')
                printwrap(
                    f'{Font.error_bold} Error: {Font.error}Entity and element tags '
                    f'aren\'t supported in dat files.{Font.end}{next_status}', 'error')
                sys.exit()

        # Check for a valid Redump XML dat that follows the Logiqx dtd
        validation_tags = ['<datafile>', '<?xml', '<game', '<header']

        for i, validation_tag in enumerate(validation_tags):
            validation_tags[i] = bool(list(filter(lambda x: validation_tag in x, input_dat.contents)))
            continue

        if functools.reduce(lambda a,b: a + b, validation_tags) == len(validation_tags):
            try:
                for i, line in enumerate(input_dat.contents):
                    # Remove unexpected XML declarations from the file to avoid DTD check failures
                    if bool(re.search('<\?xml.*?>', line)) == True:
                        input_dat.contents[i] = input_dat.contents[i].replace(re.search('<\?xml.*?>', input_dat.contents[0])[0], '<?xml version="1.0"?>')
                    # Remove CLRMAMEPro and Romcenter declarations to avoid DTD check failures
                    if bool(re.search('.*?<(clrmamepro|romcenter).*?>', line)) == True:
                        input_dat.contents[i] = ''
                    if bool(re.search('.*?</header>', line)) == True:
                        break
            except:
                print('failed.')
                printwrap(
                    f'{Font.error_bold}* Error: {Font.error}File is missing an XML '
                    f'declaration. It\'s probably not a dat file.'
                    f'{next_status}{Font.end}', 'error')
                if is_folder == False:
                    sys.exit()
                else:
                    return 'end_batch'

            input_dat.contents = ''.join(input_dat.contents)

            try:
                with open('datafile.dtd') as dtdfile:
                    dtd = etree.DTD(dtdfile)
                    try:
                        root = etree.XML(input_dat.contents)

                        if dtd.validate(root) == False:
                            print('failed.')
                            printwrap(
                                f'{Font.error_bold}* Error: {Font.error}XML file '
                                f'doesn\'t conform to Logiqx dtd. '
                                f'{dtd.error_log.last_error}.'
                                f'{next_status}{Font.end}', 'error')
                            if is_folder == False:
                                sys.exit()
                            else:
                                return 'end_batch'
                    except etree.XMLSyntaxError as e:
                        print('failed.')
                        printwrap(
                            f'{Font.error_bold}* Error: {Font.error}XML file is '
                            f'malformed. {e}.{next_status}{Font.end}', 'error')
                        if is_folder == False:
                            sys.exit()
                        else:
                            return 'end_batch'
                    else:
                        if gui == False:
                            print('file is a Logiqx dat file.')

            except OSError as e:
                printwrap(f'{Font.error_bold}* Error: {str(e)}{next_status}{Font.end}',
                          'error')
                if is_folder == False:
                    raise
                else:
                    return 'end_batch'
        else:
            print('failed.')
            printwrap(
                f'{Font.error_bold}* Error: "{dat_file}"{Font.error} '
                f'isn\'t a compatible dat file.{next_status}{Font.end}', 'error')
            if is_folder == False:
                sys.exit()
            else:
                return 'end_batch'

    if gui == False:
        # Convert contents to BeautifulSoup object, remove original contents attribute
        print('* Converting dat file to a searchable format... ', sep=' ', end='', flush=True)
        input_dat.soup = BeautifulSoup(input_dat.contents, "lxml-xml")
        del input_dat.contents
        print('done.')

        # Set input dat header details
        if input_dat.soup.find('header') != None:
            for key, value in input_dat.__dict__.items():
                if (
                    key != 'soup'
                    and key != 'user_options'
                    and value == 'Unknown'
                    and input_dat.soup.find(key) != None):
                    setattr(input_dat, key, input_dat.soup.find(key).string)
                elif value == '':
                    setattr(input_dat, key, 'Unknown')
    else:
        # Hacky quick search of the dat so we can set a system filter name
        # quickly on larger files.
        for line in input_dat.contents.splitlines():
            if bool(re.search('<name>.*</name>', line)) == True:
                input_dat.name = re.search('<name>.*</name>', line)[0]
                input_dat.name = input_dat.name[6:-7]

        input_dat.name = input_dat.name.replace('&amp;', '&')

        for line in input_dat.contents.splitlines():
            if bool(re.search('<url>.*</url>', line)) == True:
                input_dat.url = re.search('<url>.*</url>', line)[0]
                input_dat.url = input_dat.url[5:-6]

    # Remove Retool tag from name if it exists
    input_dat.name = re.sub(' \(Retool.*?\)', '', input_dat.name)

    # Sanitize some header details which are used in the output filename
    characters = [':', '\\', '/', '<', '>', '"', '|', '?', '*']
    reserved_filenames = ['con', 'prn', 'aux', 'nul', 'com[1-9]', 'lpt[1-9]']

    for character in characters:
        if character in input_dat.name:
            input_dat.name = input_dat.name.replace(character, '-')
        if character in input_dat.version:
            input_dat.version = input_dat.version.replace(character, '-')

    for filename in reserved_filenames:
        if re.search('^' + filename + '$', input_dat.name) != None:
            input_dat.name = 'Unknown'
        if re.search('^' + filename + '$', input_dat.version) != None:
            input_dat.version = 'Unknown'

    return input_dat


def header(input_dat, new_title_count, user_input, version):
    """ Creates a header for the output dat file """

    new_title_count = str('{:,}'.format(new_title_count))

    name = f'\n\t\t<name>{html.escape(input_dat.name, quote=False)} (Retool {version})</name>'
    description = (
        f'\n\t\t<description>{html.escape(input_dat.name, quote=False)}{user_input.user_options}'
        f' ({new_title_count}) ({input_dat.version})</description>')


    if input_dat.author != '' and input_dat.author != None:
        input_dat.author = input_dat.author.replace(' & Retool', '')
        input_dat.author = f'{html.escape(input_dat.author, quote=False)} &amp; Retool'
    else:
        input_dat.author = 'Unknown &amp; Retool'

    # Add rom headers if required
    rom_header = ''

    if 'Atari - 7800' in input_dat.name:
        rom_header = (
            f'\n\t\t<clrmamepro header="No-Intro_A7800.xml"/>'
            f'\n\t\t<romcenter plugin="a7800.dll"/>'
        )
    if 'Atari - Lynx' in input_dat.name:
        rom_header = (
            f'\n\t\t<clrmamepro header="No-Intro_LNX.xml"/>'
            f'\n\t\t<romcenter plugin="lynx.dll"/>'
            )
    if 'Nintendo - Family Computer Disk System' in input_dat.name:
        rom_header = (
            f'\n\t\t<clrmamepro header="No-Intro_FDS.xml"/>'
            f'\n\t\t<romcenter plugin="fds.dll"/>'
            )
    if 'Nintendo - Nintendo Entertainment System' in input_dat.name:
        rom_header = (
            f'\n\t\t<clrmamepro header="No-Intro_NES.xml"/>'
            f'\n\t\t<romcenter plugin="nes.dll"/>'
            )

    header = [
        '<?xml version="1.0"?>',
        '\n<!DOCTYPE datafile PUBLIC "-//Logiqx//DTD ROM Management Datafile//EN" '
        '"http://www.logiqx.com/Dats/datafile.dtd">',
        '\n<datafile>',
        '\n\t<header>',
        name,
        description,
        f'\n\t\t<version>{html.escape(input_dat.version, quote=False)}</version>',
        f'\n\t\t<date>{datetime.datetime.now().strftime("%Y-%m-%d %H-%M-%S")}</date>',
        f'\n\t\t<author>{input_dat.author}</author>',
        '\n\t\t<homepage>http://www.github.com/unexpectedpanda/retool</homepage>',
        f'\n\t\t<url>{html.escape(input_dat.url, quote=False)}</url>',
        rom_header,
        '\n\t</header>\n']
    return header