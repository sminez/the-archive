import libtcodpy as libtcod
import math
import textwrap
import shelve

'''
# <--!> is a TODO comment
# <--> is a section heading

>> libtcod built in colours::    http://doryen.eptalys.net/data/libtcod/doc/1.5.1/html2/color.html

BUGS::
ai sometimes not chasing player
level up hp going over max [fixed??]
elevator not perma-visible after discovery

TODO::
world gen - look at a beter alg that gives less corridors and a more varied layout
varied AI - basic, pack, hunter, thief, sneaky, brute, ranged, caster
the attack algorithm - pwr=base_atk + base_bns + wep_rng +- luck_factor (if max then crit)
enemy equipment and drops - humanoids drop their equipment, creatures drop certain items?
more items and equipment
NPCs
skils and classes

console_wait_for_keypress needs to change to sys_wait_for_event ??

'''

##########################################################################################
##########################################################################################

'''
###############################
## <--> Define global values ##
###############################
'''


# Display parameters
SCREEN_WIDTH = 65
SCREEN_HEIGHT = 45

MAP_WIDTH = 80
MAP_HEIGHT = 50

CAMERA_WIDTH = 65
CAMERA_HEIGHT = 38

LIMIT_FPS = 20

# Sizes and coordinates relevant for the GUI
BAR_WIDTH = 20
PANEL_HEIGHT = 7
PANEL_Y = SCREEN_HEIGHT - PANEL_HEIGHT
MSG_X = BAR_WIDTH + 2
MSG_WIDTH = SCREEN_WIDTH - BAR_WIDTH - 2
MSG_HEIGHT = PANEL_HEIGHT - 1
INVENTORY_WIDTH = 50
LEVEL_SCREEN_WIDTH = 40
CHARACTER_SCREEN_WIDTH = 30
HELP_SCREEN_WIDTH = 50

# The list of game messages and their colours, starts empty
game_msgs = []

# Map generation parameters
color_dark_wall = libtcod.darkest_azure
color_light_wall = libtcod.desaturated_orange
color_dark_ground = libtcod.darker_azure
color_light_ground = libtcod.desaturated_amber

ROOM_MAX_SIZE = 12
ROOM_MIN_SIZE = 7
MAX_ROOMS = 60

LEVEL_UP_BASE = 100
LEVEL_UP_FACTOR = 120

NEW_FLOOR_HEAL = 10

# Set up for the FOV/Lighting mechanics {NOTE:: the default FOV alg is 0}
FOV_ALGO = 2
FOV_LIGHT_WALLS = True
TORCH_RADIUS = 7
fov_noise = libtcod.noise_new(1, 1.0, 1.0)

##########################################################################################
##########################################################################################


'''
###############################
## <--> Tech and item values ##
###############################
'''

# Healing
heal_small = 40
heal_medium = 70
heal_large = 120

# Damage Dealing
SHOCK_DAMAGE = 40
SHOCK_RANGE = 5

# Grenades
GRENADO_RADIUS = 2
GRENADO_DAMAGE = 25

# Buff / Debuff
CONFUSE_RANGE = 6
CONFUSE_NUM_TURNS = 10

##########################################################################################
##########################################################################################

'''
############################
## <--> Class definitions ##
############################
'''


class Object:
  # This is a generic game object {the player, an enemy, an item, the elevator...}
  # It is always represented by a character on screen.
  def __init__(self, x, y, char, name, colour, blocks=False, always_visible=False, fighter=None, ai=None, item=None, equipment=None):
    self.x = x
    self.y = y
    self.char = char
    self.name = name
    self.colour = colour
    self.blocks = blocks
    self.always_visible = always_visible

    self.fighter = fighter
    if self.fighter:  #let the fighter component know who owns it
      self.fighter.owner = self

    self.ai = ai
    if self.ai:  #let the AI component know who owns it
      self.ai.owner = self

    self.item = item
    if self.item:  #let the Item component know who owns it
      self.item.owner = self

    self.equipment = equipment
    if self.equipment:  #let the Equipment component know who owns it
      self.equipment.owner = self
      #there must be an Item component for the Equipment component to work properly
      self.item = Item()
      self.item.owner = self


  def move(self, dx, dy):
    #Move the object character by a given amount after checking to see if the next tile is blocked
    if not is_blocked(self.x + dx, self.y + dy):
      self.x += dx
      self.y += dy

  def move_towards(self, target_x, target_y):
    #vector from this object to the target, and distance
    dx = target_x - self.x
    dy = target_y - self.y
    distance = math.sqrt(dx ** 2 + dy ** 2)
    #normalize it to length 1 (preserving direction), then round it and
    #convert to integer so the movement is restricted to the map grid
    dx = int(round(dx // distance))
    dy = int(round(dy // distance))
    self.move(dx, dy)

  def distance_to(self, other):
    #return the distance to another object
    dx = other.x - self.x
    dy = other.y - self.y
    return math.sqrt(dx ** 2 + dy ** 2)

  def distance(self, x, y):
    #return the distance to some coordinates
    return math.sqrt((x - self.x) ** 2 + (y - self.y) ** 2)

  def send_to_back(self):
    #make this object be drawn first, so all others appear above it if they're in the same tile.
    global objects
    objects.remove(self)
    objects.insert(0, self)

  def draw(self):
    #only show if it's visible to the player
    if libtcod.map_is_in_fov(fov_map, self.x, self.y):
      (x, y) = to_camera_coordinates(self.x, self.y)
      if x is not None:
        #set the color and then draw the character that represents this object at its position
        libtcod.console_set_default_foreground(con, self.colour)
        libtcod.console_put_char(con, x, y, self.char, libtcod.BKGND_NONE)

  def clear(self):
    #erase the character that represents this object
    (x, y) = to_camera_coordinates(self.x, self.y)
    if x is not None:
      libtcod.console_put_char(con, x, y, ' ', libtcod.BKGND_NONE)

#################################################################################################################################

class Tile:
  #Define a tile on the map and its properties: can it be traversed, can you see through it
  def __init__(self, blocked, block_sight = None):
    self.blocked = blocked
    self.explored = False
  #By default, if a tile is blocked, it also blocks sight
    if block_sight is None:
      block_sight = blocked
      self.block_sight = block_sight

#################################################################################################################################

class Rect:
  def __init__(self, x, y, w, h):
    self.x1 = x
    self.y1 = y
    self.x2 = x + w
    self.y2 = y + h

  def center(self):
    center_x = (self.x1 + self.x2) / 2
    center_y = (self.y1 + self.y2) / 2
    return (center_x, center_y)

  def intersect(self, other):
  # Returns Boolean True if this rectangle intersects with another one already on the map
  # Note that (x1,y1) is the top left corner and (x2,y2) is the bottom right
    return (self.x1 <= other.x2 and self.x2 >= other.x1 and self.y1 <= other.y2 and self.y2 >= other.y1)

#################################################################################################################################

class Item:
  # An item that can be picked up and used.
  def __init__(self, use_function=None, function_var=None):
    self.use_function = use_function
    self.function_var = function_var

  def pick_up(self):
    # Add the item to the player's inventory and remove it from the map
    if len(inventory) >= 26:
      message('Your inventory is full, cannot pick up ' + self.owner.name + '!!', libtcod.red)
    else:
      inventory.append(self.owner)
      objects.remove(self.owner)
      message('You picked up a ' + self.owner.name + '!', libtcod.green)
      #special case: automatically equip, if the corresponding equipment slot is unused
      equipment = self.owner.equipment
      if equipment and get_equipped_in_slot(equipment.slot) is None:
        equipment.equip()

  def use(self):
    # Special case: if the object has the Equipment component, the "use" action is to equip/dequip
    if self.owner.equipment:
      self.owner.equipment.toggle_equip()
      return
    # Otherwise, just call the "use_function" if it is defined
    if self.use_function is None:
      message('The ' + self.owner.name + ' cannot be used.')
    else:
      if self.use_function() != 'cancelled':
        inventory.remove(self.owner)  #destroy after use, unless it was cancelled for some reason

  def drop(self):
    #special case: if the object has the Equipment component, dequip it before dropping
    if self.owner.equipment:
      self.owner.equipment.dequip()
    #add to the map and remove from the player's inventory. also, place it at the player's coordinates
    objects.append(self.owner)
    inventory.remove(self.owner)
    self.owner.x = player.x
    self.owner.y = player.y
    message('You dropped a ' + self.owner.name + '.', libtcod.yellow)

#################################################################################################################################

class Equipment:
  # Component for an object that can be equipped. automatically adds the Item component.
  # <--!> add aditional bonuses as we go!
  def __init__(self, slot, power_bonus=0, defense_bonus=0, max_hp_bonus=0, max_sp_bonus=0):
    self.power_bonus = power_bonus
    self.defense_bonus = defense_bonus
    self.max_hp_bonus = max_hp_bonus
    self.max_sp_bonus = max_sp_bonus
    self.slot = slot
    self.is_equipped = False

  def toggle_equip(self):  #toggle equip/dequip status
    if self.is_equipped:
      self.dequip()
    else:
      self.equip()

  def equip(self):
    # If the slot is already being used, dequip whatever is there first
    old_equipment = get_equipped_in_slot(self.slot)
    if old_equipment is not None:
      old_equipment.dequip()
    # Equip the item
    self.is_equipped = True
    message('Equipped ' + self.owner.name + ' on ' + self.slot + '.', libtcod.light_green)

  def dequip(self):
    #dequip object and show a message about it
    if not self.is_equipped: return
    self.is_equipped = False
    message('Dequipped ' + self.owner.name + ' from ' + self.slot + '.', libtcod.light_yellow)

#################################################################################################################################
#################################################################################################################################


'''
###################################
## <--> Magic and item functions ## >> NOTE::need to work out how to vary function parameters!
###################################
'''


def get_equipped_in_slot(slot):  #returns the equipment in a slot, or None if it's empty
  for obj in inventory:
    if obj.equipment and obj.equipment.slot == slot and obj.equipment.is_equipped:
      return obj.equipment
  return None

#################################################################################################################################

def get_all_equipped(obj):  #returns a list of equipped items
  if obj == player:
    equipped_list = []
    for item in inventory:
      if item.equipment and item.equipment.is_equipped:
        equipped_list.append(item.equipment)
    return equipped_list
  else:
    # <--!> Add in functionality here to allow for enemies to use equipment
    return []  # other objects have no equipment

#################################################################################################################################

def closest_enemy(max_range):
  #find closest enemy, up to a maximum range, and in the player's FOV
  closest_so_far = None
  closest_dist = max_range + 1  #start with (slightly more than) maximum range
  for object in objects:
    if object.fighter and not object == player and libtcod.map_is_in_fov(fov_map, object.x, object.y):
      #calculate distance between this object and the player
      dist = player.distance_to(object)
      if dist < closest_dist:  #it's closer, so remember it
        closest_so_far = object
        closest_dist = dist
  return closest_so_far

#################################################################################################################################

def heal():
  #heal the player
  if player.fighter.hp == player.fighter.max_hp:
    message('You are already at full health!', libtcod.red)
    return 'cancelled'
  message("You gulp down the strange liquid and feel...better?!", libtcod.light_violet)
  player.fighter.heal(heal_small)

#################################################################################################################################

def cast_shock():
  #find closest enemy (inside a maximum range) and damage it
  enemy = closest_enemy(SHOCK_RANGE)
  if enemy is None:  #no enemy found within maximum range
    message('You toss the jar in your hands...', libtcod.red)
    return 'cancelled'
  #zap it!
  message('A burst of static electricity strikes the ' + enemy.name + ' for ' + str(SHOCK_DAMAGE) + ' points of damage!', libtcod.light_blue)
  enemy.fighter.take_damage(SHOCK_DAMAGE)

#################################################################################################################################

def cast_confuse():
  #ask the player for a target to confuse
  message('Left-click an enemy to confuse it, or right-click to cancel.', libtcod.light_cyan)
  enemy = target_enemy(CONFUSE_RANGE)
  if enemy is None:
    return 'cancelled'
  #replace the enemy's AI with a "confused" one; after some turns it will restore the old AI
  old_ai = enemy.ai
  enemy.ai = ConfusedEnemy(old_ai)
  enemy.ai.owner = enemy  #tell the new component who owns it
  message('The eyes of the ' + enemy.name + ' look vacant, as their lungs fill with spores.', libtcod.light_green)

#################################################################################################################################

def grenado():
    #ask the player for a target tile to throw a grenade at
    message('Left-click a target tile for the plasma grenade, or right-click to cancel.', libtcod.light_cyan)
    (x, y) = target_tile()
    if x is None: return 'cancelled'
    message('The grenado explodes, throwing shrapnel over ' + str(GRENADO_RADIUS) + ' tiles!', libtcod.orange)

    for obj in objects:  #damage every fighter in range, including the player
        if obj.distance(x, y) <= GRENADO_RADIUS and obj.fighter:
            message('The ' + obj.name + ' gets scorched for ' + str(GRENADO_DAMAGE) + ' damage.', libtcod.orange)
            obj.fighter.take_damage(GRENADO_DAMAGE)

#################################################################################################################################
#################################################################################################################################


'''
##################################
## <--> AI and class components ##
##################################
'''


class Fighter:
  # This component contains combat-related properties and methods (for enemies, player, NPCs).
  def __init__(self, hp, defense, power, xp, sp=0, death_function=None):
    self.base_max_hp = hp
    self.hp = hp
    self.base_defense = defense
    self.base_power = power
    self.xp = xp
    self.base_max_sp = sp
    self.sp = sp
    self.death_function = death_function

  @property
  def power(self):  #return actual power, by summing up the bonuses from all equipped items
    bonus = sum(equipment.power_bonus for equipment in get_all_equipped(self.owner))
    return self.base_power + bonus

  @property
  def defense(self):  #return actual defense, by summing up the bonuses from all equipped items
    bonus = sum(equipment.defense_bonus for equipment in get_all_equipped(self.owner))
    return self.base_defense + bonus

  @property
  def max_hp(self):  #return actual max_hp, by summing up the bonuses from all equipped items
    bonus = sum(equipment.max_hp_bonus for equipment in get_all_equipped(self.owner))
    return self.base_max_hp + bonus

  @property
  def max_sp(self):  #return actual max_hp, by summing up the bonuses from all equipped items
    bonus = sum(equipment.max_sp_bonus for equipment in get_all_equipped(self.owner))
    return self.base_max_sp + bonus

  def take_damage(self, damage):
    #apply damage if possible
    if damage > 0:
      self.hp -= damage
    #check for death. if there's a death function, call it
    if self.hp <= 0:
      function = self.death_function
      if function is not None:
        function(self.owner)
      if self.owner != player:  #yield experience to the player
        player.fighter.xp += self.xp

  def attack(self, target):
    #a simple formula for attack damage
    damage = self.power - target.fighter.defense
    if damage > 0:
      #make the target take some damage
      message(self.owner.name.capitalize() + ' attacks ' + target.name + ' for ' + str(damage) + ' hit points.')
      target.fighter.take_damage(damage)
    else:
      message(self.owner.name.capitalize() + ' attacks ' + target.name + ' but it has no effect!')

  def heal(self, amount):
    #heal by the given amount, without going over the maximum
    self.hp += amount
    if self.hp > self.max_hp:
      self.hp = self.max_hp

#################################################################################################################################

class BasicEnemy:
  #AI for a basic enemy.
  def take_turn(self):
    #a basic enemy takes its turn. If you can see it, it can see you
    enemy = self.owner
    if libtcod.map_is_in_fov(fov_map, enemy.x, enemy.y):
    #move towards player if far away
      if enemy.distance_to(player) >= 2:
        enemy.move_towards(player.x, player.y)
      #close enough, attack! (if the player is still alive.)
      elif player.fighter.hp > 0:
        enemy.fighter.attack(player)

#################################################################################################################################

class ConfusedEnemy:
  #AI for a temporarily confused enemy (reverts to previous AI after a while).
  def __init__(self, old_ai, num_turns=CONFUSE_NUM_TURNS):
    self.old_ai = old_ai
    self.num_turns = num_turns

  def take_turn(self):
    if self.num_turns > 0:  #still confused...
      #move in a random direction, and decrease the number of turns confused
      self.owner.move(libtcod.random_get_int(0, -1, 1), libtcod.random_get_int(0, -1, 1))
      self.num_turns -= 1
    else:  #restore the previous AI (this one will be deleted because it's not referenced anymore)
      self.owner.ai = self.old_ai
      message('The ' + self.owner.name + ' coughs violently and snaps out of their confusion!', libtcod.red)

#################################################################################################################################
#################################################################################################################################


'''
##########################
## <--> Death functions ##
##########################
'''


def player_death(player):
  #the game ended!
  global game_state
  message('Alas, you have come to the end of your journey...for this time.')
  game_state = 'dead'
  # Remove character and leave their body.
  player.char = '%'
  player.colour = libtcod.dark_red

#################################################################################################################################

def enemy_death(enemy):
  #transform it into a nasty corpse! it doesn't block, can't be
  #attacked and doesn't move
  message('The ' + enemy.name + ' was defeated! You gain ' + str(enemy.fighter.xp) + ' experience points.', libtcod.orange)
  enemy.char = '%'
  enemy.colour = libtcod.dark_red
  enemy.blocks = False
  enemy.fighter = None
  enemy.ai = None
  enemy.name = 'remains of ' + enemy.name
  enemy.send_to_back()

#################################################################################################################################
#################################################################################################################################


'''
##############################
## <--> Interface functions ##
##############################
'''


def handle_keys():
  global key;
  if key.vk == libtcod.KEY_ENTER and key.lalt:
    #Alt+Enter: toggle fullscreen
    libtcod.console_set_fullscreen(not libtcod.console_is_fullscreen())
  elif key.vk == libtcod.KEY_ESCAPE:
    return 'exit'  #exit game

  #Check that the player is alive!
  if game_state == 'playing':
    #Move the player character using the arrow keys
    if key.vk == libtcod.KEY_UP:
      player_move_or_attack(0, -1)
    elif key.vk == libtcod.KEY_DOWN:
      player_move_or_attack(0, 1)
    elif key.vk == libtcod.KEY_LEFT:
      player_move_or_attack(-1, 0)
    elif key.vk == libtcod.KEY_RIGHT:
      player_move_or_attack(1, 0)
    else:

      '''
   #movement keys
        if key.vk == libtcod.KEY_UP or key.vk == libtcod.KEY_KP8:
            player_move_or_attack(0, -1)
        elif key.vk == libtcod.KEY_DOWN or key.vk == libtcod.KEY_KP2:
            player_move_or_attack(0, 1)
        elif key.vk == libtcod.KEY_LEFT or key.vk == libtcod.KEY_KP4:
            player_move_or_attack(-1, 0)
        elif key.vk == libtcod.KEY_RIGHT or key.vk == libtcod.KEY_KP6:
            player_move_or_attack(1, 0)
        elif key.vk == libtcod.KEY_HOME or key.vk == libtcod.KEY_KP7:
            player_move_or_attack(-1, -1)
        elif key.vk == libtcod.KEY_PAGEUP or key.vk == libtcod.KEY_KP9:
            player_move_or_attack(1, -1)
        elif key.vk == libtcod.KEY_END or key.vk == libtcod.KEY_KP1:
            player_move_or_attack(-1, 1)
        elif key.vk == libtcod.KEY_PAGEDOWN or key.vk == libtcod.KEY_KP3:
            player_move_or_attack(1, 1)
        elif key.vk == libtcod.KEY_KP5:
            pass  #do nothing ie wait for the monster to come to you
      '''


      #test for other keys
      key_char = chr(key.c)
      if key_char == 'g':
        #pick up an item
        for object in objects:  #look for an item in the player's tile
          if object.x == player.x and object.y == player.y and object.item:
            object.item.pick_up()
            #break

      if key.vk == libtcod.KEY_TAB:
        #show the inventory
        chosen_item = inventory_menu('Press the key next to an item to use it, or any other to cancel.\n')
        if chosen_item is not None:
          chosen_item.use()

      if key_char == 'd':
        #show the inventory; if an item is selected, drop it
        chosen_item = inventory_menu('Press the key next to an item to drop it, or any other to cancel.\n')
        if chosen_item is not None:
          chosen_item.drop()

      if key_char == 'c':
        #show character information
        level_up_xp = LEVEL_UP_BASE + player.level * LEVEL_UP_FACTOR
        msgbox('Character Information\n\nLevel: ' + str(player.level) + '\nExperience: ' + str(player.fighter.xp) +
        '\nExperience to level up: ' + str(level_up_xp) + '\n\nMaximum HP: ' + str(player.fighter.max_hp) +
        '\nAttack: ' + str(player.fighter.power) + '\nDefense: ' + str(player.fighter.defense), CHARACTER_SCREEN_WIDTH)

      if key.vk == libtcod.KEY_F1:
        #show help screen
        msgbox('For Your Information\n\n This help screen:: F1\n Toggle Full Screen:: ALT+ENTER\n Inventory:: Tab\n Character Details:: c\n ' +
               'Pick up item:: g\n Drop Item:: d', HELP_SCREEN_WIDTH)

      if key_char == '<':
        # go down elevator, if the player is on them
        if elevator.x == player.x and elevator.y == player.y:
          next_level()

      return 'didnt-take-turn'

##########################################################################################################################

def get_names_under_mouse():
  global mouse
  #return a string with the names of all objects under the mouse
  (x, y) = (mouse.cx, mouse.cy)
  (x, y) = (camera_x + x, camera_y + y)
  #create a list with the names of all objects at the mouse's coordinates and in FOV
  names = [obj.name for obj in objects if obj.x == x and obj.y == y and libtcod.map_is_in_fov(fov_map, obj.x, obj.y)]
  names = ', '.join(names)  #join the names, separated by commas
  return names

##########################################################################################################################

def target_tile(max_range=None):
  #return the position of a tile left-clicked in player's FOV (optionally in a range), or (None,None) if right-clicked.
  global key, mouse
  while True:
    #render the screen. this erases the inventory and shows the names of objects under the mouse.
    libtcod.console_flush()
    libtcod.sys_check_for_event(libtcod.EVENT_KEY_PRESS|libtcod.EVENT_MOUSE,key,mouse)
    render_all()
    (x, y) = (mouse.cx, mouse.cy)
    (x, y) = (camera_x + x, camera_y + y)
    #accept the target if the player clicked in FOV, and in case a range is specified, if it's in that range
    if (mouse.lbutton_pressed and libtcod.map_is_in_fov(fov_map, x, y) and (max_range is None or player.distance(x, y) <= max_range)):
      return (x, y)

    if mouse.rbutton_pressed or key.vk == libtcod.KEY_ESCAPE:
      message('::Aborted::', libtcod.red)
      return (None, None)  #cancel if the player right-clicked or pressed Escape

##########################################################################################################################

def target_enemy(max_range=None):
  #returns a clicked enemy inside FOV up to a range, or None if right-clicked
  while True:
    (x, y) = target_tile(max_range)
    if x is None:  #player cancelled
      return None
    #return the first clicked enemy, otherwise continue looping
    for obj in objects:
      if obj.x == x and obj.y == y and obj.fighter and obj != player:
        return obj

##########################################################################################################################

def move_camera(target_x, target_y):
  global camera_x, camera_y, fov_recompute

  #new camera coordinates (top-left corner of the screen relative to the map)
  x = target_x - CAMERA_WIDTH / 2  #coordinates so that the target is at the center of the screen
  y = target_y - CAMERA_HEIGHT / 2

  #make sure the camera doesn't see outside the map
  if x < 0: x = 0
  if y < 0: y = 0
  if x > MAP_WIDTH - CAMERA_WIDTH - 1: x = MAP_WIDTH - CAMERA_WIDTH - 1
  if y > MAP_HEIGHT - CAMERA_HEIGHT - 1: y = MAP_HEIGHT - CAMERA_HEIGHT - 1
  if x != camera_x or y != camera_y: fov_recompute = True
  (camera_x, camera_y) = (x, y)

##########################################################################################################################

def to_camera_coordinates(x, y):
  #convert coordinates on the map to coordinates on the screen
  (x, y) = (x - camera_x, y - camera_y)
  if (x < 0 or y < 0 or x >= CAMERA_WIDTH or y >= CAMERA_HEIGHT):
    return (None, None)  #if it's outside the view, return nothing
  return (x, y)

##########################################################################################################################

def render_all():
  global fov_map, color_dark_wall, color_light_wall
  global color_dark_ground, color_light_ground
  global fov_recompute
  global camera_x, camera_y

  move_camera(player.x, player.y)

  if fov_recompute:
  # Recompute FOV if needed (the player moved or something)
    fov_recompute = False
    libtcod.map_compute_fov(fov_map, player.x, player.y, TORCH_RADIUS, FOV_LIGHT_WALLS, FOV_ALGO)
    libtcod.console_clear(con)
  # Go through all tiles, and set their background color according to the FOV
    for y in range(CAMERA_HEIGHT):
      for x in range(CAMERA_WIDTH):
        (map_x, map_y) = (camera_x + x, camera_y + y)
        visible = libtcod.map_is_in_fov(fov_map, map_x, map_y)
        wall = map[map_x][map_y].block_sight
        if not visible:
          # It's out of the player's FOV
          if map[map_x][map_y].explored:
            if wall:
              libtcod.console_set_char_background(con, x, y, color_dark_wall, libtcod.BKGND_SET)
            else:
              libtcod.console_set_char_background(con, x, y, color_dark_ground, libtcod.BKGND_SET)
        else:
          # It's visible
          if wall:
            libtcod.console_set_char_background(con, x, y, color_light_wall, libtcod.BKGND_SET )
          else:
            libtcod.console_set_char_background(con, x, y, color_light_ground, libtcod.BKGND_SET )
          # Explore the current tile
          map[map_x][map_y].explored = True

  # Draw all objects in the list
  for object in objects:
    if object != player:
      object.draw()
    player.draw()

  # Blit the contents of the offscreen "con" buffer to the root console
  libtcod.console_blit(con, 0, 0, MAP_WIDTH, MAP_HEIGHT, 0, 0, 0)
  # Prepare to render the GUI panel
  libtcod.console_set_default_background(panel, libtcod.black)
  libtcod.console_clear(panel)
  #print the game messages, one line at a time
  y = 1
  for (line, color) in game_msgs:
    libtcod.console_set_default_foreground(panel, color)
    libtcod.console_print_ex(panel, MSG_X, y, libtcod.BKGND_NONE, libtcod.LEFT, line)
    y += 1
  # Show the player's stats
  render_bar(1, 1, BAR_WIDTH, 'HP', player.fighter.hp, player.fighter.max_hp, libtcod.flame, libtcod.darker_flame)
  render_bar(1, 2, BAR_WIDTH, 'SP', player.fighter.sp, player.fighter.max_sp, libtcod.dark_sea, libtcod.darker_sea)
  libtcod.console_print_ex(panel, 1, 4, libtcod.BKGND_NONE, libtcod.LEFT, 'Archive Depth:: ' + str(archive_depth))
  #display names of objects under the mouse
  libtcod.console_set_default_foreground(panel, libtcod.light_gray)
  libtcod.console_print_ex(panel, 1, 0, libtcod.BKGND_NONE, libtcod.LEFT, get_names_under_mouse())
  # Blit the contents of "panel" to the root console
  libtcod.console_blit(panel, 0, 0, SCREEN_WIDTH, PANEL_HEIGHT, 0, 0, PANEL_Y)

##########################################################################################################################

def player_move_or_attack(dx, dy):
  global fov_recompute
  # The coordinates the player is moving to/attacking
  x = player.x + dx
  y = player.y + dy

  # Try to find an attackable object there
  target = None
  for object in objects:
    if object.fighter and object.x == x and object.y == y:
      target = object
      break

  # Attack the target if there is one, otherwise move into the tile
  if target is not None:
    player.fighter.attack(target)
  else:
    player.move(dx, dy)
    fov_recompute = True

##########################################################################################################################

def save_game():
  # Open a new empty shelve (possibly overwriting an old one) to write the game data
  file = shelve.open('game_data/savegame', 'n')
  file['map'] = map
  file['objects'] = objects
  file['player_index'] = objects.index(player)  #index of player in objects list
  file['inventory'] = inventory
  file['game_msgs'] = game_msgs
  file['game_state'] = game_state
  file['elevator_index'] = objects.index(elevator)
  file['archive_depth'] = archive_depth
  file.close()

##########################################################################################################################

def load_game():
  #open the previously saved shelve and load the game data
  global map, objects, player, inventory, game_msgs, game_state, archive_depth, elevator
  file = shelve.open('game_data/savegame', 'r')
  map = file['map']
  objects = file['objects']
  player = objects[file['player_index']]  #get index of player in objects list and access it
  inventory = file['inventory']
  game_msgs = file['game_msgs']
  game_state = file['game_state']
  elevator = objects[file['elevator_index']]
  archive_depth = file['archive_depth']
  file.close()

  initialise_FOV()

##########################################################################################################################

def msgbox(text, width=50):
  menu(text, [], width)  #use menu() as a sort of "message box"

##########################################################################################################################

def render_bar(x, y, total_width, name, value, maximum, bar_color, back_color):
  #render a bar (HP, experience, etc). first calculate the width of the bar
  bar_width = int(float(value) / maximum * total_width)
  #render the background first
  libtcod.console_set_default_background(panel, back_color)
  libtcod.console_rect(panel, x, y, total_width, 1, False, libtcod.BKGND_SCREEN)
  #now render the bar on top
  libtcod.console_set_default_background(panel, bar_color)
  if bar_width > 0:
    libtcod.console_rect(panel, x, y, bar_width, 1, False, libtcod.BKGND_SCREEN)
  libtcod.console_set_default_foreground(panel, libtcod.white)
  libtcod.console_print_ex(panel, x + total_width / 2, y, libtcod.BKGND_NONE, libtcod.CENTER, name + ': ' + str(value) + '/' + str(maximum))

##########################################################################################################################

def message(new_msg, color = libtcod.white):
  #split the message if necessary, among multiple lines
  new_msg_lines = textwrap.wrap(new_msg, MSG_WIDTH)
  for line in new_msg_lines:
    #if the buffer is full, remove the first line to make room for the new one
    if len(game_msgs) == MSG_HEIGHT:
      del game_msgs[0]
      #add the new line as a tuple, with the text and the color
    game_msgs.append( (line, color) )

##########################################################################################################################

def menu(header, options, width):
  if len(options) > 26: raise ValueError('Cannot have a menu with more than 26 options .')
  #calculate total height for the header (after auto-wrap) and one line per option
  header_height = libtcod.console_get_height_rect(con, 0, 0, width, SCREEN_HEIGHT, header)
  if header == '':
    header_height = 0
  height = len(options) + header_height

  #create an off-screen console that represents the menu's window
  window = libtcod.console_new(width, height)

  #print the header, with auto-wrap
  libtcod.console_set_default_foreground(window, libtcod.white)
  libtcod.console_print_rect_ex(window, 0, 0, width, height, libtcod.BKGND_NONE, libtcod.LEFT, header)

  #print all the options
  y = header_height
  letter_index = ord('a')
  for option_text in options:
    text = '(' + chr(letter_index) + ') ' + option_text
    libtcod.console_print_ex(window, 0, y, libtcod.BKGND_NONE, libtcod.LEFT, text)
    y += 1
    letter_index += 1

  #blit the contents of "window" to the root console
  x = SCREEN_WIDTH/2 - width/2
  y = SCREEN_HEIGHT/2 - height/2
  libtcod.console_blit(window, 0, 0, width, height, 0, x, y, 1.0, 0.7)

  #present the root console to the player and wait for a key-press
  libtcod.console_flush()
  key = libtcod.console_wait_for_keypress(True)

  #convert the ASCII code to an index; if it corresponds to an option, return it
  index = key.c - ord('a')
  if index >= 0 and index < len(options):
    return index
  return None

##########################################################################################################################

def inventory_menu(header):
  #show a menu with each item of the inventory as an option
  if len(inventory) == 0:
    options = ['Inventory is empty.']
  else:
    options = []
    for item in inventory:
      text = item.name
      #show additional information, in case it's equipped
      if item.equipment and item.equipment.is_equipped:
        text = text + ' (on ' + item.equipment.slot + ')'
      options.append(text)

  index = menu(header, options, INVENTORY_WIDTH)
  #if an item was chosen, return it
  if index is None or len(inventory) == 0: return None
  return inventory[index].item

##########################################################################################################################

def random_choice_index(chances):  #choose one option from list of chances, returning its index
  #the dice will land on some number between 1 and the sum of the chances
  dice = libtcod.random_get_int(0, 1, sum(chances))
  #go through all chances, keeping the sum so far
  running_sum = 0
  choice = 0
  for w in chances:
    running_sum += w
    #see if the dice landed in the part that corresponds to this choice
    if dice <= running_sum:
      return choice
    choice += 1

##########################################################################################################################

def random_choice(chances_dict):
  #choose one option from dictionary of chances, returning its key
  chances = chances_dict.values()
  strings = chances_dict.keys()
  return strings[random_choice_index(chances)]

##########################################################################################################################
##########################################################################################################################


'''
##############################
## <--> World Gen functions ##
##############################
'''


def from_archive_depth(table):
  #returns a value that depends on archive depth. the table specifies what value occurs after each level, default is 0.
  for (value, level) in reversed(table):
    if archive_depth >= level:
      return value
  return 0

##########################################################################################################################

def make_map():
  global map, player, objects, elevator
  objects = [player]

  #Fill the map with blocked tiles
  map = [[Tile(True) for y in range(MAP_HEIGHT)] for x in range(MAP_WIDTH)]
  # Now to populate the map by 'carving out' rooms and tunnels
  rooms = []
  num_rooms = 0

  for r in range(MAX_ROOMS):
    # Select a random width and height for each room between the specified max/min
    # NOTE:: the '0' argument below determines the 'stream' to select the random number from
    # Look at the documentation for more details
    w = libtcod.random_get_int(0, ROOM_MIN_SIZE, ROOM_MAX_SIZE)
    h = libtcod.random_get_int(0, ROOM_MIN_SIZE, ROOM_MAX_SIZE)
    # Place the new room in a random position without going out of the boundaries of the map
    x = libtcod.random_get_int(0, 0, MAP_WIDTH - w - 1)
    y = libtcod.random_get_int(0, 0, MAP_HEIGHT - h - 1)
    new_room = Rect(x, y, w, h)
    # Run through the other rooms and see if they intersect with this one
    failed = False
    for other_room in rooms:
      if new_room.intersect(other_room):
        failed = True
        break
    if not failed:
      # This means there are no intersections, so this room is valid and can be 'carved out'
      create_room(new_room)
      # Populate the room
      place_objects(new_room)
      # Find the center coordinates of new room (will be useful later)
      (new_x, new_y) = new_room.center()
      # This is the first room, where the player starts at
      if num_rooms == 0:
        player.x = new_x
        player.y = new_y
      else:
        # For all rooms after the first: connect it to the previous room with a tunnel
        # Take center coordinates of previous room
        (prev_x, prev_y) = rooms[num_rooms-1].center()
        # Toss a coin (random number that is either 0 or 1)
        if libtcod.random_get_int(0, 0, 1) == 1:
          # First move horizontally, then vertically
          create_h_tunnel(prev_x, new_x, prev_y)
          create_v_tunnel(prev_y, new_y, new_x)
        else:
          # First move vertically, then horizontally
          create_v_tunnel(prev_y, new_y, prev_x)
          create_h_tunnel(prev_x, new_x, new_y)
        # Append the new room to the list
      rooms.append(new_room)
      num_rooms += 1
  #create an elevator at the center of the last room
  elevator = Object(new_x, new_y, '<', 'Elevator', libtcod.white, always_visible=True)
  objects.append(elevator)
  elevator.send_to_back()  #so it's drawn below the enemies

##########################################################################################################################

def next_level():
  global archive_depth, ini
  #advance to the next level
  message('You take a moment to rest and recover your strength while you wait for the elevator.', libtcod.light_violet)
  player.fighter.heal(NEW_FLOOR_HEAL)  #heal the player by NEW_FLOOR_HEAL

  message('As the elevator shudders to a halt you hear the rope snap and you step out, ready to proceed deeper into the heart of the Archive...', libtcod.light_violet)
  archive_depth += 1
  make_map()  #create a fresh new level!
  initialise_FOV()

##########################################################################################################################

def create_room(room):
  global map
  #Work through the tiles in a rectangle and make them passable
  for x in range(room.x1 + 1, room.x2):
    for y in range(room.y1 +1, room.y2):
      map[x][y].blocked = False
      map[x][y].block_sight = False

##########################################################################################################################

def create_h_tunnel(x1, x2, y):
  # This will 'carve out' a horizontal tunnel between (x1,y) and (x2,y)
  global map
  for x in range(min(x1, x2), max(x1, x2) + 1):
    map[x][y].blocked = False
    map[x][y].block_sight = False

##########################################################################################################################

def create_v_tunnel(y1, y2, x):
    global map
    # This will 'carve out' a horizontal tunnel between (x,y1) and (x,y2)
    for y in range(min(y1, y2), max(y1, y2) + 1):
        map[x][y].blocked = False
        map[x][y].block_sight = False

##########################################################################################################################

def place_objects(room):
  #NOTE:: from_archive_depth([[value,depth_1], [value,depth_2]])
  max_enemies = from_archive_depth([[2, 1], [3, 4], [5, 6], [6, 9], [8, 10]])
  max_items = from_archive_depth([[1, 1], [2, 4], [3, 7]])

  enemy_chances = {}
  enemy_chances['rat'] = from_archive_depth([[35, 1], [30, 3], [25, 5], [0, 7]])
  enemy_chances['thief'] = from_archive_depth([[15, 1], [30, 3], [60, 5], [0,7]])
  enemy_chances['dog'] = from_archive_depth([[20, 2], [30, 4], [40, 6]])
  enemy_chances['Curator'] = from_archive_depth([[10, 3], [30, 5], [60, 7]])

  item_chances = {}
  item_chances['heal'] = 40
  item_chances['shock'] = from_archive_depth([[25, 4]])
  item_chances['grenado'] = from_archive_depth([[25, 6]])
  item_chances['confuse'] = from_archive_depth([[10, 2]])
  item_chances['sword'] = from_archive_depth([[10, 4]])
  item_chances['shield'] = from_archive_depth([[10, 6]])

  # Choose random number of enemies
  num_enemies = libtcod.random_get_int(0, 0, max_enemies)
  for i in range(num_enemies):
    # Choose random spot for the enemy
    x = libtcod.random_get_int(0, room.x1+1, room.x2-1)
    y = libtcod.random_get_int(0, room.y1+1, room.y2-1)
    #only place it if the tile is not blocked
    if not is_blocked(x, y):
      # % chances: 20% VI, 40% security guard, 1% agent, 39% guard dog
      choice = random_choice(enemy_chances)
      if choice == 'dog':
        fighter_component = Fighter(hp=15, defense=0, power=4, xp=25, death_function=enemy_death)
        ai_component = BasicEnemy()
        enemy = Object(x, y, 'd', 'dog', libtcod.desaturated_sea, blocks=True, fighter=fighter_component, ai=ai_component)
      elif choice == 'thief':
        fighter_component = Fighter(hp=20, defense=2, power=5, xp=40, death_function=enemy_death)
        ai_component = BasicEnemy()
        enemy = Object(x, y, 'h', 'thief', libtcod.light_grey, blocks=True, fighter=fighter_component, ai=ai_component)
      elif choice == 'Curator':
        fighter_component = Fighter(hp=40, defense=3, power=8, xp=70, death_function=enemy_death)
        ai_component = BasicEnemy()
        enemy = Object(x, y, 'C', 'Curator', libtcod.crimson, blocks=True, fighter=fighter_component, ai=ai_component)
      elif choice == 'rat':
        fighter_component = Fighter(hp=5, defense=0, power=3, xp=10, death_function=enemy_death)
        ai_component = BasicEnemy()
        enemy = Object(x, y, 'r', 'rat', libtcod.light_grey, blocks=True, fighter=fighter_component, ai=ai_component)
      objects.append(enemy)

  #choose random number of items
  num_items = libtcod.random_get_int(0, 0, max_items)
  for i in range(num_items):
    #choose random spot for this item
    x = libtcod.random_get_int(0, room.x1+1, room.x2-1)
    y = libtcod.random_get_int(0, room.y1+1, room.y2-1)
    #only place it if the tile is not blocked
    if not is_blocked(x, y):
      choice = random_choice(item_chances)
      if choice == "heal":
        item_component = Item(use_function=heal, function_var=heal_small)
        item = Object(x, y, '!', 'strange bottle', libtcod.chartreuse, item=item_component)
      elif choice == "shock":
        item_component = Item(use_function=cast_shock)
        item = Object(x, y, '&', 'leyden jar', libtcod.light_yellow, item=item_component)
      elif choice == "confuse":
        item_component = Item(use_function=cast_confuse)
        item = Object(x, y, '&', 'mysterious powder', libtcod.light_yellow, item=item_component)
      elif choice == "grenado":
        item_component = Item(use_function=grenado)
        item = Object(x, y, ';', 'grenado', libtcod.flame, item=item_component)
      elif choice == 'sword':
        equipment_component = Equipment(slot='right hand', power_bonus=3)
        item = Object(x, y, '/', 'steel sword', libtcod.sky, equipment=equipment_component)
      elif choice == 'shield':
        equipment_component = Equipment(slot='left hand', defense_bonus=1)
        item = Object(x, y, '[', 'wooden shield', libtcod.darker_orange, equipment=equipment_component)



      objects.append(item)
      item.send_to_back()  #items appear below other objects

##########################################################################################################################

def is_blocked(x, y):
  # First test to see if the map tile is blocked
  if map[x][y].blocked:
    return True
  # Now check for any blocking objects on that tile
  for object in objects:
    if object.blocks and object.x == x and object.y == y:
      return True
  return False

##########################################################################################################################
##########################################################################################################################


'''
###############################
## <--> Character management ##
###############################
'''

def check_level_up():
  #see if the player's experience is enough to level-up
  level_up_xp = LEVEL_UP_BASE + player.level * LEVEL_UP_FACTOR
  if player.fighter.xp >= level_up_xp:
    player.level += 1
    player.fighter.max_hp += 5
    player.fighter.max_sp += 2
    message('Your time in the Archive has changed you... [You are now level ' + str(player.level) + '!]', libtcod.yellow)
    player.fighter.xp -= level_up_xp
    choice = None
    while choice == None:  #keep asking until a choice is made
      choice = menu('Level up! Choose a stat to raise:\n',
      ['Constitution (+10 HP, from ' + str(player.fighter.max_hp) + '\nand restored to full hp)',
      'Strength (+1 attack, from ' + str(player.fighter.power) + ')',
      'Agility (+1 defense, from ' + str(player.fighter.defense) + ')'], LEVEL_SCREEN_WIDTH)
      if choice == 0:
        player.fighter.base_max_hp += 10
        player.fighter.hp += 10
        player.fighter.heal(heal_small)
      elif choice == 1:
        player.fighter.base_power += 1
      elif choice == 2:
        player.fighter.base_defense += 1


##########################################################################################################################
##########################################################################################################################


'''
#######################################
## <--> INITIALISATION AND MAIN LOOP ##
#######################################
'''

def main_menu():
  global key;
  img = libtcod.image_load('art/menu_background.png')
  while not libtcod.console_is_window_closed():
    #show the background image, at twice the regular console resolution
    libtcod.image_blit_2x(img, 0, 0, 0)
    #show the game's title, and some credits!
    libtcod.console_set_default_foreground(0, libtcod.light_yellow)
    libtcod.console_print_ex(0, SCREEN_WIDTH/2, SCREEN_HEIGHT/2-4, libtcod.BKGND_NONE, libtcod.CENTER,'A Short Future History of the Universe That Was')
    libtcod.console_print_ex(0, SCREEN_WIDTH/2, SCREEN_HEIGHT-2, libtcod.BKGND_NONE, libtcod.CENTER,'By IDAM')
    #show options and wait for the player's choice
    choice = menu('', ['Play a new game', 'Continue last game', 'Quit'], 24)

    if choice == 0:  #new game
      new_game()
      play_game()
    if choice == 1:  #load last game
      try:
        load_game()
      except:
        msgbox('\n No saved game to load.\n', 24)
        continue
      play_game()
    elif choice == 2:  #quit
      break

    if key.vk == libtcod.KEY_ENTER and key.lalt:
      #(special case) Alt+Enter: toggle fullscreen
      libtcod.console_set_fullscreen(not libtcod.console_is_fullscreen())

##########################################################################################################################

def new_game():
  global player, inventory, game_msgs, game_state, archive_depth

  # Initialise the player character
  fighter_component = Fighter(hp=100, defense=1, power=2, sp=20, xp= 0, death_function=player_death)
  player = Object(0, 0, '@', 'player', libtcod.light_cyan, blocks=True, fighter=fighter_component)
  player.level = 1
  inventory = []

  # <--!> Initial equipment: at the moment this is set but allow this to vary with class
  equipment_component = Equipment(slot='right hand', power_bonus=2)
  obj = Object(0, 0, '|', 'silver-tipped cain', libtcod.silver, equipment=equipment_component)
  inventory.append(obj)
  equipment_component.equip()
  obj.always_visible = True

  game_msgs = []
  # Generate the dungeon
  archive_depth = 1
  make_map()
  initialise_FOV()
  # Now we are up and running!
  game_state = 'playing'
    # Welcome message
  message('Greetings traveler! Welcome to The Archive: home of the future history of the universe. We hope you enjoy your stay!', libtcod.amber)

##########################################################################################################################

def initialise_FOV():
  global fov_map, fov_recompute
  fov_recompute = True
  libtcod.console_clear(con)  #unexplored areas start black (which is the default background color)
  # Generate the FOV map
  fov_map = libtcod.map_new(MAP_WIDTH, MAP_HEIGHT)
  for y in range(MAP_HEIGHT):
    for x in range(MAP_WIDTH):
      libtcod.map_set_properties(fov_map, x, y, not map[x][y].block_sight, not map[x][y].blocked)

  libtcod.console_clear(con)  #unexplored areas start black (which is the default background color)

##########################################################################################################################

def play_game():
  global key, mouse
  global camera_x, camera_y
  player_action = None

  mouse = libtcod.Mouse()
  key = libtcod.Key()

  (camera_x, camera_y) = (0, 0)

  # The main loop will run as long as the window is open
  while not libtcod.console_is_window_closed():
    libtcod.sys_check_for_event(libtcod.EVENT_KEY_PRESS|libtcod.EVENT_MOUSE,key,mouse)
    render_all()
    libtcod.console_flush()
    check_level_up()
    # Erase all objects before they are drawn in again
    for object in objects:
      object.clear()
    # Check for input
    player_action = handle_keys()
    if player_action == 'exit':
      save_game()
      break
    # Let the enemies take their turn
    if game_state == 'playing' and player_action != 'didnt-take-turn':
      for object in objects:
        if object.ai:
          object.ai.take_turn()


##########################################################################################################################
##########################################################################################################################

# dejavu16x16_gs_tc
# arial10x10

# Set the font and framerate
libtcod.console_set_custom_font('dejavu16x16_gs_tc.png', libtcod.FONT_TYPE_GREYSCALE | libtcod.FONT_LAYOUT_TCOD)
libtcod.sys_set_fps(LIMIT_FPS)
# Initialise the screen
libtcod.console_init_root(SCREEN_WIDTH, SCREEN_HEIGHT, '<<::ASFHoTUTW::>> V0.2', False)
# Initialise an offscreen console to allow buffering/layering and blitting of multiple objects without having to write to the screen
con = libtcod.console_new(MAP_WIDTH, MAP_HEIGHT)
# Initialise the HUD
panel = libtcod.console_new(SCREEN_WIDTH, PANEL_HEIGHT)

main_menu()
