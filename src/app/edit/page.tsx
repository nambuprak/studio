
"use client";

import Link from 'next/link';
import { useState, useEffect, Suspense } from 'react';
import { useSearchParams, useRouter } from 'next/navigation';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Textarea } from '@/components/ui/textarea';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogTrigger } from '@/components/ui/dialog';
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Checkbox } from "@/components/ui/checkbox";
import { ArrowLeft, PlusCircle, Edit, Trash2, Edit3, Loader2, Home } from 'lucide-react';

interface Repository {
  id: string;
  project_name: string;
}

interface AdditionalInfoItem {
  id: string; // Client-side ID
  title: string;
  description: string;
}

type InputType = 'folder' | 'url';

const generateClientId = () => 'id-' + Date.now().toString(36) + Math.random().toString(36).substring(2);

function EditPageContent() {
  const searchParams = useSearchParams();
  const router = useRouter();

  const [selectedTutorId, setSelectedTutorId] = useState<string>('');
  const [allTutors, setAllTutors] = useState<Repository[]>([]);

  // Form field states
  const [projectName, setProjectName] = useState<string>('');
  const [inputType, setInputType] = useState<InputType>('folder');
  const [sourceLocation, setSourceLocation] = useState<string>('');
  const [repoOverview, setRepoOverview] = useState<string>('');
  const [tapBap, setTapBap] = useState<string>('');
  const [fileTypes, setFileTypes] = useState<string>('');
  const [excludeFolders, setExcludeFolders] = useState<string>('');
  const [embedRepo, setEmbedRepo] = useState<boolean>(false);
  const [additionalInfoList, setAdditionalInfoList] = useState<AdditionalInfoItem[]>([]);
  
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [isUpdating, setIsUpdating] = useState<boolean>(false);
  const [isDeleting, setIsDeleting] = useState<boolean>(false);
  const [isModalOpen, setIsModalOpen] = useState<boolean>(false);
  const [currentInfoTitle, setCurrentInfoTitle] = useState<string>('');
  const [currentInfoDescription, setCurrentInfoDescription] = useState<string>('');
  const [editingId, setEditingId] = useState<string | null>(null);

  // Status modal for re-processing (similar to create page)
  const [isStatusModalOpen, setIsStatusModalOpen] = useState<boolean>(false);
  const [statusMessage, setStatusMessage] = useState<string>('');
  const [isProcessingComplete, setIsProcessingComplete] = useState<boolean>(false);
  const [pollingIntervalId, setPollingIntervalId] = useState<NodeJS.Timeout | null>(null);
  // No need for isTutorCreationComplete here, edit page doesn't "create"

  // Fetch all tutors for the dropdown
  useEffect(() => {
    async function fetchAllTutorsForSelect() {
      setIsLoading(true);
      try {
        const response = await fetch('/api/repos');
        if (!response.ok) throw new Error(`Failed to fetch tutors list: ${response.statusText}`);
        const data: Repository[] = await response.json();
        setAllTutors(data.map(t => ({ id: t.id, project_name: t.project_name || "Unnamed Tutor" })));
        
        const tutorIdFromQuery = searchParams.get('repoId');
        if (tutorIdFromQuery && data.some(t => t.id === tutorIdFromQuery)) {
          setSelectedTutorId(tutorIdFromQuery);
        } else if (tutorIdFromQuery) {
          alert("The tutor ID from the URL was not found. Please select from the list.");
          router.replace('/edit'); // Clear invalid repoId from URL
        }
      } catch (error: any) {
        console.error("Failed to fetch tutors list:", error);
        alert(`Could not fetch tutors list: ${error.message}`);
        setAllTutors([]);
      }
      setIsLoading(false);
    }
    fetchAllTutorsForSelect();
  }, [searchParams, router]);

  // Fetch details for the selected tutor
  useEffect(() => {
    async function fetchTutorDetails(tutorId: string) {
      if (!tutorId) {
        handleClearForm(false);
        return;
      }
      setIsLoading(true);
      try {
        const response = await fetch(`/api/tutor-details/${tutorId}`);
        if (!response.ok) throw new Error(`Failed to fetch tutor details: ${response.statusText}`);
        const details = await response.json();

        setProjectName(details.project_name || '');
        setInputType(details.input_type || 'folder');
        setSourceLocation(details.source_location || '');
        setRepoOverview(details.repo_overview || '');
        setTapBap(details.tap_bap || '');
        setFileTypes(details.file_types || '');
        setExcludeFolders(details.exclude_folders || '');
        setEmbedRepo(details.embed_repo === 1 || details.embed_repo === true);
        
        const formattedAdditionalInfo = (details.additional_info_list || []).map((item: any) => ({
            ...item,
            id: generateClientId() 
        }));
        setAdditionalInfoList(formattedAdditionalInfo);

      } catch (error: any) {
        console.error(`Failed to fetch details for tutor ${tutorId}:`, error);
        alert(`Could not load details for the selected tutor: ${error.message}`);
        handleClearForm(false);
      }
      setIsLoading(false);
    }

    if (selectedTutorId) {
      fetchTutorDetails(selectedTutorId);
    } else {
      handleClearForm(false);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedTutorId]);

  // Status polling logic (similar to create page)
  const fetchUpdateStatus = async (tutorId: string) => {
    try {
      const response = await fetch(`/api/tutor-status/${tutorId}`);
      if (!response.ok) { /* ... error handling ... */ return; }
      const statusData = await response.json();
      setStatusMessage(statusData.message || 'Re-processing...');
      if (statusData.status === 'COMPLETED' || statusData.status === 'FAILED') {
        setIsProcessingComplete(true);
        if (pollingIntervalId) clearInterval(pollingIntervalId);
        setPollingIntervalId(null);
        // Optionally show a success/failure alert here
        alert(statusData.status === 'COMPLETED' ? "Re-processing finished successfully." : "Re-processing failed.");
      }
    } catch (error) { /* ... error handling ... */ }
  };

  useEffect(() => {
    if (selectedTutorId && isStatusModalOpen && !isProcessingComplete) {
      fetchUpdateStatus(selectedTutorId);
      const intervalId = setInterval(() => fetchUpdateStatus(selectedTutorId), 3000);
      setPollingIntervalId(intervalId);
      return () => { if (intervalId) clearInterval(intervalId); setPollingIntervalId(null); };
    } else if (pollingIntervalId && (isProcessingComplete || !isStatusModalOpen)) {
      clearInterval(pollingIntervalId);
      setPollingIntervalId(null);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedTutorId, isStatusModalOpen, isProcessingComplete]);


  const handleSourceTypeChange = (value: string) => {
    setInputType(value as InputType);
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
      alert("Title cannot be empty.");
      return;
    }
    if (editingId) {
      setAdditionalInfoList(additionalInfoList.map(item =>
        item.id === editingId ? { ...item, title: currentInfoTitle, description: currentInfoDescription } : item
      ));
    } else {
      setAdditionalInfoList([...additionalInfoList, { id: generateClientId(), title: currentInfoTitle, description: currentInfoDescription }]);
    }
    setIsModalOpen(false);
    setCurrentInfoTitle('');
    setCurrentInfoDescription('');
    setEditingId(null);
  };

  const handleDeleteAdditionalInfo = (id: string) => {
    setAdditionalInfoList(additionalInfoList.filter(item => item.id !== id));
  };

  const handleUpdate = async () => {
    if (!selectedTutorId) {
      alert("Please select a tutor to update.");
      return;
    }
    if (!projectName.trim()) {
      alert('Project Name cannot be empty.');
      return;
    }
     if (!sourceLocation.trim()) {
      alert(`Please enter the ${inputType === 'folder' ? 'folder path' : 'repository URL'}.`);
      return;
    }

    setIsUpdating(true);
    const payload = {
      project_name: projectName,
      input_type: inputType,
      source_location: sourceLocation,
      repo_overview: repoOverview,
      tap_bap: tapBap,
      file_types: fileTypes,
      exclude_folders: excludeFolders,
      additional_info_list: additionalInfoList.map(({ id, ...rest }) => rest), 
      embed_repo: embedRepo,
    };

    try {
      const response = await fetch(`/api/tutor-details/${selectedTutorId}`, { 
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const result = await response.json();
      if (!response.ok) {
        throw new Error(result.error || result.details || `Server error: ${response.status}`);
      }
      
      setIsUpdating(false);
      if (embedRepo && response.status === 202 && result.tutor_id) { // 202 means re-processing started
        setStatusMessage(result.message || "Re-processing initiated...");
        setIsProcessingComplete(false);
        setIsStatusModalOpen(true);
      } else {
        alert("Self Tutor updated successfully!");
      }
      // Re-fetch all tutors to reflect potential name changes in the dropdown
      const updatedTutors = allTutors.map(t => t.id === selectedTutorId ? {...t, project_name: projectName} : t);
      setAllTutors(updatedTutors);

    } catch (error: any) {
      console.error("Failed to update Self Tutor:", error);
      alert(`Failed to update Self Tutor: ${error.message}`);
      setIsUpdating(false);
    }
  };

  const handleDeleteTutor = async () => {
    if (!selectedTutorId) {
      alert("Please select a tutor to delete.");
      return;
    }
    if (confirm(`Are you sure you want to delete the tutor "${projectName || 'this tutor'}"? This action cannot be undone and will remove associated embedded data.`)) {
      setIsDeleting(true);
      try {
        const response = await fetch(`/api/tutor-details/${selectedTutorId}`, { method: 'DELETE' });
        if (!response.ok) {
          const result = await response.json().catch(() => ({}));
          throw new Error(result.error || `Failed to delete: ${response.statusText}`);
        }
        alert("Self Tutor deleted successfully.");
        
        const newTutorList = allTutors.filter(t => t.id !== selectedTutorId);
        setAllTutors(newTutorList);
        if (newTutorList.length > 0) {
          setSelectedTutorId(newTutorList[0].id); 
        } else {
          setSelectedTutorId(''); 
          handleClearForm(true);
        }
        router.replace('/edit'); // Refresh or navigate to clean state

      } catch (error: any) {
        console.error("Failed to delete Self Tutor:", error);
        alert(`Failed to delete Self Tutor: ${error.message}`);
      }
      setIsDeleting(false);
    }
  };

  const handleClearForm = (clearTutorSelection = true) => {
    if (clearTutorSelection) {
      setSelectedTutorId('');
    }
    setProjectName('');
    setInputType('folder');
    setSourceLocation('');
    setRepoOverview('');
    setTapBap('');
    setFileTypes('');
    setExcludeFolders('');
    setEmbedRepo(false);
    setAdditionalInfoList([]);
  };

  const formDisabled = isLoading || isUpdating || isDeleting || isStatusModalOpen;

  return (
    <main className="min-h-screen bg-background flex flex-col items-center py-8 px-4 sm:px-6 md:px-8">
      <Card className="w-full max-w-3xl shadow-xl rounded-lg">
        <CardHeader>
          <CardTitle className="text-3xl font-bold text-primary flex items-center">
            <Edit3 className="mr-3 h-8 w-8" /> Edit Self Tutor
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-6">
          <div className="space-y-2">
            <Label htmlFor="repo-select-edit" className="text-base font-semibold">Select Tutor to Edit</Label>
            <Select 
              value={selectedTutorId} 
              onValueChange={(value) => setSelectedTutorId(value)} 
              disabled={allTutors.length === 0 || isLoading || isUpdating || isDeleting}
            >
              <SelectTrigger id="repo-select-edit" className="w-full text-base py-2.5">
                <SelectValue placeholder="Choose a tutor..." />
              </SelectTrigger>
              <SelectContent>
                {allTutors.length > 0 ? (
                  allTutors.map((tutor) => (
                    <SelectItem key={tutor.id} value={tutor.id} className="text-base">
                      {tutor.project_name} (ID: {tutor.id.substring(0,6)}...)
                    </SelectItem>
                  ))
                ) : (
                   <SelectItem value="loading" disabled className="text-base">
                     {isLoading ? "Loading tutors..." : "No tutors found. Create one first."}
                  </SelectItem>
                )}
              </SelectContent>
            </Select>
          </div>
          
          {isLoading && selectedTutorId && <div className="flex justify-center items-center p-4"><Loader2 className="h-6 w-6 animate-spin" /> Loading tutor details...</div>}

          {!selectedTutorId && !isLoading && allTutors.length > 0 &&
            <div className="text-center text-muted-foreground p-6">Please select a tutor from the dropdown to edit its details.</div>
          }
           {!selectedTutorId && !isLoading && allTutors.length === 0 &&
            <div className="text-center text-muted-foreground p-6">No tutors available to edit. Please create one first.</div>
          }


          {selectedTutorId && !isLoading && (
            <>
              <div className="space-y-2">
                <Label htmlFor="project-name-edit" className="text-base font-semibold">Project Name</Label>
                <Input
                  id="project-name-edit"
                  type="text"
                  value={projectName}
                  onChange={(e) => setProjectName(e.target.value)}
                  placeholder="e.g., My Awesome Project"
                  className="text-base py-3 h-14"
                  disabled={formDisabled}
                />
              </div>

              <div className="space-y-2">
                <Label className="text-base font-semibold">Source Type</Label>
                <RadioGroup value={inputType} onValueChange={handleSourceTypeChange} className="flex space-x-4">
                  <div className="flex items-center space-x-2">
                    <RadioGroupItem value="folder" id="folder-edit" disabled={formDisabled} />
                    <Label htmlFor="folder-edit" className={formDisabled ? "text-muted-foreground" : ""}>Folder Directory</Label>
                  </div>
                  <div className="flex items-center space-x-2">
                    <RadioGroupItem value="url" id="url-edit" disabled={formDisabled} />
                    <Label htmlFor="url-edit" className={formDisabled ? "text-muted-foreground" : ""}>Repository URL</Label>
                  </div>
                </RadioGroup>
              </div>
              
              <div className="space-y-2">
                <Label htmlFor="source-location-edit" className="text-base font-semibold">
                  {inputType === 'folder' ? 'Project Folder Path' : 'Repository URL'}
                </Label>
                <Input
                  id="source-location-edit"
                  type="text"
                  value={sourceLocation}
                  onChange={(e) => setSourceLocation(e.target.value)}
                  placeholder={inputType === 'folder' ? 'e.g., /path/to/your/local/project' : 'e.g., https://github.com/your-username/your-repo.git'}
                  className="text-base py-3 h-14"
                  disabled={formDisabled}
                />
              </div>

              <h2 className="text-xl font-semibold text-foreground pt-2">Repository Overview</h2>
              <div className="space-y-2">
                <Label htmlFor="repo-overview-edit" className="sr-only">Repository Overview</Label>
                <Textarea
                  id="repo-overview-edit"
                  placeholder="Describe the repository, its purpose, key technologies, etc."
                  value={repoOverview}
                  onChange={(e) => setRepoOverview(e.target.value)}
                  className="w-full min-h-[12rem] text-base"
                  disabled={formDisabled}
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="tap-bap-edit" className="text-base font-semibold">TAP / BAP</Label>
                <Input
                  id="tap-bap-edit"
                  value={tapBap}
                  onChange={(e) => setTapBap(e.target.value)}
                  placeholder="e.g., Technical Audience Profile / Business Audience Profile"
                  className="text-base"
                  disabled={formDisabled}
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="file-types-edit" className="text-base font-semibold">File Types (comma-separated)</Label>
                <Input
                  id="file-types-edit"
                  value={fileTypes}
                  onChange={(e) => setFileTypes(e.target.value)}
                  placeholder="e.g., .ts, .tsx, .md, .py"
                  className="text-base"
                  disabled={formDisabled}
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="exclude-folders-edit" className="text-base font-semibold">Exclude Folders (comma-separated)</Label>
                <Input
                  id="exclude-folders-edit"
                  value={excludeFolders}
                  onChange={(e) => setExcludeFolders(e.target.value)}
                  placeholder="e.g., node_modules, .git, dist"
                  className="text-base"
                  disabled={formDisabled}
                />
              </div>

              <div className="space-y-4 pt-4 border-t">
                <h3 className="text-lg font-semibold text-foreground">Additional Specific Details</h3>
                <Dialog open={isModalOpen} onOpenChange={setIsModalOpen}>
                  <DialogTrigger asChild>
                    <Button variant="outline" onClick={openModalForAdd} disabled={formDisabled}>
                      <PlusCircle className="mr-2 h-5 w-5" /> Add Additional Info
                    </Button>
                  </DialogTrigger>
                  <DialogContent className="sm:max-w-[500px]">
                    <DialogHeader>
                      <DialogTitle>{editingId ? 'Edit' : 'Add'} Additional Info</DialogTitle>
                    </DialogHeader>
                    <div className="grid gap-4 py-4">
                       <div className="grid grid-cols-4 items-center gap-x-4 gap-y-2">
                        <Label htmlFor="info-title-edit" className="text-right col-span-1">
                          Title
                        </Label>
                        <Input
                          id="info-title-edit"
                          value={currentInfoTitle}
                          onChange={(e) => setCurrentInfoTitle(e.target.value)}
                          className="col-span-3"
                          placeholder="e.g., Authentication Flow"
                        />
                      </div>
                      <div className="grid grid-cols-4 items-start gap-x-4 gap-y-2">
                        <Label htmlFor="info-description-edit" className="text-right col-span-1 pt-2">
                          Description
                        </Label>
                        <Textarea
                          id="info-description-edit"
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
                            <Button variant="ghost" size="icon" onClick={() => openModalForEdit(info.id)} className="h-8 w-8" disabled={formDisabled}>
                              <Edit className="h-4 w-4" />
                            </Button>
                            <Button variant="ghost" size="icon" onClick={() => handleDeleteAdditionalInfo(info.id)} className="h-8 w-8 text-destructive hover:text-destructive" disabled={formDisabled}>
                              <Trash2 className="h-4 w-4" />
                            </Button>
                          </div>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
              
              <div className="items-center flex space-x-2 pt-4 border-t mt-4">
                <Checkbox id="embed-repo-edit" checked={embedRepo} onCheckedChange={(checked) => setEmbedRepo(Boolean(checked))} disabled={formDisabled} />
                <Label htmlFor="embed-repo-edit" className={`text-sm font-medium leading-none ${formDisabled ? "text-muted-foreground" : ""}`}>
                  Embed Repository/Folder Content (re-processes files server-side if source or settings change)
                </Label>
              </div>
            </>
          )}


          <div className="flex flex-col sm:flex-row justify-end space-y-3 sm:space-y-0 sm:space-x-3 pt-6 border-t mt-6">
             <Link href="/" passHref legacyBehavior>
              <Button variant="outline" size="lg" className="w-full sm:w-auto" disabled={isLoading || isUpdating || isDeleting}>
                <Home className="mr-2 h-5 w-5" /> Go Home
              </Button>
            </Link>
            <Button variant="outline" size="lg" onClick={() => handleClearForm(false)} className="w-full sm:w-auto" disabled={!selectedTutorId || isLoading || isUpdating || isDeleting}>
              Clear Changes
            </Button>
             <Button variant="destructive" size="lg" onClick={handleDeleteTutor} className="w-full sm:w-auto" disabled={!selectedTutorId || isLoading || isUpdating || isDeleting}>
              {isDeleting && <Loader2 className="mr-2 h-5 w-5 animate-spin" />}
              <Trash2 className="mr-2 h-5 w-5" /> Delete Tutor
            </Button>
            <Button size="lg" onClick={handleUpdate} className="w-full sm:w-auto" disabled={!selectedTutorId || isLoading || isUpdating || isDeleting}>
              {isUpdating && <Loader2 className="mr-2 h-5 w-5 animate-spin" />}
              Update Self Tutor
            </Button>
          </div>
        </CardContent>
      </Card>
      
      {/* Status Modal for Re-processing on Update */}
      <Dialog open={isStatusModalOpen} onOpenChange={(open) => { if(!open && isProcessingComplete) setIsStatusModalOpen(false); else if (!open) setIsStatusModalOpen(false); else setIsStatusModalOpen(true); }}>
        <DialogContent className="sm:max-w-[425px]" onPointerDownOutside={(e) => { if(!isProcessingComplete) e.preventDefault();}}>
          <DialogHeader>
            <DialogTitle>Re-processing Tutor Content</DialogTitle>
          </DialogHeader>
          <div className="grid gap-4 py-4">
            <div className="flex items-center justify-center space-x-2">
              {!isProcessingComplete && <Loader2 className="h-5 w-5 animate-spin text-primary" />}
              <p className="text-sm text-muted-foreground">{statusMessage}</p>
            </div>
          </div>
          <DialogFooter>
            <Button onClick={() => setIsStatusModalOpen(false)} disabled={!isProcessingComplete}>
              Close
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

    </main>
  );
}

export default function EditPage() {
  return (
    <Suspense fallback={<div className="flex justify-center items-center min-h-screen"><Loader2 className="h-8 w-8 animate-spin text-primary" /> Loading...</div>}>
      <EditPageContent />
    </Suspense>
  );
}

    