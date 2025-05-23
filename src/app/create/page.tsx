
"use client";

import Link from 'next/link';
import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
// Removed Select components as they are no longer used for repo selection here
import { Textarea } from '@/components/ui/textarea';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogTrigger, DialogClose } from '@/components/ui/dialog';
import { ArrowLeft, PlusSquare, PlusCircle, Edit, Trash2 } from 'lucide-react';

interface AdditionalInfoItem {
  id: string;
  title: string;
  description: string;
}

export default function CreatePage() {
  const [selectedRepo, setSelectedRepo] = useState<string>(''); // Will now store the selected folder name
  const [repoOverview, setRepoOverview] = useState<string>('');
  const [tapBap, setTapBap] = useState<string>('');
  const [fileTypes, setFileTypes] = useState<string>('');
  const [excludeFolders, setExcludeFolders] = useState<string>('');

  const [additionalInfoList, setAdditionalInfoList] = useState<AdditionalInfoItem[]>([]);
  const [isModalOpen, setIsModalOpen] = useState<boolean>(false);
  const [currentInfoTitle, setCurrentInfoTitle] = useState<string>('');
  const [currentInfoDescription, setCurrentInfoDescription] = useState<string>('');
  const [editingId, setEditingId] = useState<string | null>(null);

  const handleFolderSelect = (event: React.ChangeEvent<HTMLInputElement>) => {
    if (event.target.files && event.target.files.length > 0) {
      let displayName = '';
      const firstItem = event.target.files[0];
      // webkitRelativePath is present when a directory is selected.
      // It gives the path relative to the selected directory, e.g., "FolderName/file.txt".
      // We extract "FolderName".
      if (firstItem.webkitRelativePath) {
        displayName = firstItem.webkitRelativePath.split('/')[0];
      } else {
        // Fallback if it's a single file or webkitdirectory is not fully supported/used.
        displayName = firstItem.name;
      }
      setSelectedRepo(displayName);
    } else {
      setSelectedRepo('');
    }
  };

  const openModalForAdd = () => {
    setEditingId(null);
    setCurrentInfoTitle('');
    setCurrentInfoDescription('');
    setIsModalOpen(true);
  };

  const openModalForEdit = (id: string) => {
    const itemToEdit = additionalInfoList.find(item => item.id === id);
    if (itemToEdit) {
      setEditingId(id);
      setCurrentInfoTitle(itemToEdit.title);
      setCurrentInfoDescription(itemToEdit.description);
      setIsModalOpen(true);
    }
  };

  const handleSaveAdditionalInfo = () => {
    if (!currentInfoTitle.trim()) {
      alert("Title cannot be empty."); // Simple validation
      return;
    }
    if (editingId) {
      setAdditionalInfoList(additionalInfoList.map(item =>
        item.id === editingId ? { ...item, title: currentInfoTitle, description: currentInfoDescription } : item
      ));
    } else {
      setAdditionalInfoList([...additionalInfoList, { id: crypto.randomUUID(), title: currentInfoTitle, description: currentInfoDescription }]);
    }
    setIsModalOpen(false);
    setCurrentInfoTitle('');
    setCurrentInfoDescription('');
    setEditingId(null);
  };

  const handleDeleteAdditionalInfo = (id: string) => {
    setAdditionalInfoList(additionalInfoList.filter(item => item.id !== id));
  };
  
  const handleGenerate = () => {
    if (!selectedRepo.trim()) {
      alert("Please select a project folder.");
      return;
    }
    console.log("Generating self tutor with data:", {
      selectedRepo, // This is now the folder name
      repoOverview,
      tapBap,
      fileTypes,
      excludeFolders,
      additionalInfoList,
    });
    alert("Self Tutor generation initiated (see console for data).");
  };

  const handleClearForm = () => {
    setSelectedRepo('');
    setRepoOverview('');
    setTapBap('');
    setFileTypes('');
    setExcludeFolders('');
    setAdditionalInfoList([]);
    // Reset file input visually (optional, browser-dependent)
    const fileInput = document.getElementById('project-folder-input') as HTMLInputElement;
    if (fileInput) {
      fileInput.value = '';
    }
    console.log("Form cleared.");
  };

  return (
    <main className="min-h-screen bg-background flex flex-col items-center py-8 px-4 sm:px-6 md:px-8">
      <Card className="w-full max-w-3xl shadow-xl rounded-lg">
        <CardHeader>
          <CardTitle className="text-3xl font-bold text-primary flex items-center">
            <PlusSquare className="mr-3 h-8 w-8" /> Create a Self Tutor
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-6">
          {/* Row 2: Select Project Folder */}
          <div className="space-y-2">
            <Label htmlFor="project-folder-input" className="text-base font-semibold">Select Project Folder</Label>
            <Input
              id="project-folder-input"
              type="file"
              // @ts-ignore because `webkitdirectory` is not in standard HTMLInputElement props
              webkitdirectory="true" 
              directory="true" // More standard but less supported attempt for directory selection
              onChange={handleFolderSelect}
              className="text-base file:mr-4 file:py-2 file:px-4 file:rounded-full file:border-0 file:text-sm file:font-semibold file:bg-primary file:text-primary-foreground hover:file:bg-primary/90"
              placeholder="No folder selected"
            />
            {selectedRepo && (
              <p className="text-sm text-muted-foreground mt-1">
                Selected: <span className="font-medium text-foreground">{selectedRepo}</span>
              </p>
            )}
          </div>

          {/* Row 3: Sub-heading */}
          <h2 className="text-xl font-semibold text-foreground pt-2">Provide a Repo Overview</h2>

          {/* Row 4: Textarea for Repo Overview */}
          <div className="space-y-2">
            <Label htmlFor="repo-overview" className="sr-only">Repository Overview</Label>
            <Textarea
              id="repo-overview"
              placeholder="Describe the repository, its purpose, key technologies, etc."
              value={repoOverview}
              onChange={(e) => setRepoOverview(e.target.value)}
              className="w-full min-h-[12rem] text-base" // Approx 6-8 lines
            />
          </div>

          {/* Row 5: TAP / BAP */}
          <div className="space-y-2">
            <Label htmlFor="tap-bap" className="text-base font-semibold">TAP / BAP</Label>
            <Input
              id="tap-bap"
              value={tapBap}
              onChange={(e) => setTapBap(e.target.value)}
              placeholder="e.g., Technical Audience Profile / Business Audience Profile"
              className="text-base"
            />
          </div>

          {/* Row 6: File Types */}
          <div className="space-y-2">
            <Label htmlFor="file-types" className="text-base font-semibold">File Types (comma-separated)</Label>
            <Input
              id="file-types"
              value={fileTypes}
              onChange={(e) => setFileTypes(e.target.value)}
              placeholder="e.g., .ts, .tsx, .md, .py"
              className="text-base"
            />
          </div>

          {/* Row 7: Exclude Folders */}
          <div className="space-y-2">
            <Label htmlFor="exclude-folders" className="text-base font-semibold">Exclude Folders (comma-separated)</Label>
            <Input
              id="exclude-folders"
              value={excludeFolders}
              onChange={(e) => setExcludeFolders(e.target.value)}
              placeholder="e.g., node_modules, .git, dist"
              className="text-base"
            />
          </div>

          {/* Row 8: Additional Info Section */}
          <div className="space-y-4 pt-4 border-t">
            <h3 className="text-lg font-semibold text-foreground">Additional Specific Details</h3>
            <Dialog open={isModalOpen} onOpenChange={setIsModalOpen}>
              <DialogTrigger asChild>
                <Button variant="outline" onClick={openModalForAdd}>
                  <PlusCircle className="mr-2 h-5 w-5" /> Add Additional Info
                </Button>
              </DialogTrigger>
              <DialogContent className="sm:max-w-[500px]">
                <DialogHeader>
                  <DialogTitle>{editingId ? 'Edit' : 'Add'} Additional Info</DialogTitle>
                </DialogHeader>
                <div className="grid gap-4 py-4">
                  <div className="grid grid-cols-4 items-center gap-x-4 gap-y-2">
                    <Label htmlFor="info-title" className="text-right col-span-1">
                      Title
                    </Label>
                    <Input
                      id="info-title"
                      value={currentInfoTitle}
                      onChange={(e) => setCurrentInfoTitle(e.target.value)}
                      className="col-span-3"
                      placeholder="e.g., Authentication Flow"
                    />
                  </div>
                  <div className="grid grid-cols-4 items-start gap-x-4 gap-y-2">
                    <Label htmlFor="info-description" className="text-right col-span-1 pt-2">
                      Description
                    </Label>
                    <Textarea
                      id="info-description"
                      value={currentInfoDescription}
                      onChange={(e) => setCurrentInfoDescription(e.target.value)}
                      className="col-span-3 min-h-[100px]"
                      placeholder="Provide detailed information..."
                    />
                  </div>
                </div>
                <DialogFooter>
                  <Button type="button" variant="outline" onClick={() => setIsModalOpen(false)}>Cancel</Button>
                  <Button type="button" onClick={handleSaveAdditionalInfo}>{editingId ? 'Save Changes' : 'Add Info'}</Button>
                </DialogFooter>
              </DialogContent>
            </Dialog>

            {additionalInfoList.length > 0 && (
              <div className="space-y-2 mt-4">
                <h4 className="text-md font-medium text-muted-foreground">Added Information:</h4>
                <ul className="border rounded-md bg-card">
                  {additionalInfoList.map((info, index) => (
                    <li key={info.id} className={`flex justify-between items-center p-3 ${index < additionalInfoList.length - 1 ? 'border-b' : ''}`}>
                      <span className="font-medium text-card-foreground break-all pr-2">{info.title}</span>
                      <div className="flex-shrink-0 space-x-1">
                        <Button variant="ghost" size="icon" onClick={() => openModalForEdit(info.id)} className="h-8 w-8">
                          <Edit className="h-4 w-4" />
                          <span className="sr-only">Edit {info.title}</span>
                        </Button>
                        <Button variant="ghost" size="icon" onClick={() => handleDeleteAdditionalInfo(info.id)} className="h-8 w-8 text-destructive hover:text-destructive">
                          <Trash2 className="h-4 w-4" />
                           <span className="sr-only">Delete {info.title}</span>
                        </Button>
                      </div>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>

          {/* Row 9: Action Buttons */}
          <div className="flex flex-col sm:flex-row justify-end space-y-3 sm:space-y-0 sm:space-x-3 pt-6 border-t mt-6">
             <Link href="/" passHref legacyBehavior>
              <Button variant="outline" size="lg" className="w-full sm:w-auto">
                <ArrowLeft className="mr-2 h-5 w-5" /> Go Home
              </Button>
            </Link>
            <Button variant="destructive" size="lg" onClick={handleClearForm} className="w-full sm:w-auto">
              Clear Form
            </Button>
            <Button size="lg" onClick={handleGenerate} className="w-full sm:w-auto">
              Generate Self Tutor
            </Button>
          </div>
        </CardContent>
      </Card>
    </main>
  );
}
